from collections.abc import Callable
from typing import Any

import pytest
from google.protobuf.message import Message

from DBDofusUnity.datas.protos.non_obf.game.challenge_pb2 import (
    ChallengeListEvent,
    ChallengeModSelectRequest,
    ChallengeProposalEvent,
    ChallengeReadyRequest,
    ChallengeResultEvent,
    ChallengeSelectedEvent,
    ChallengeSelectionRequest,
)
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import Challenge, ChallengeTarget
from DBDofusUnity.datas.protos.non_obf.game.fight_pb2 import FightTurnFinishRequest
from DBDofusUnity.datas.protos.non_obf.game.game_action_pb2 import (
    GameActionFightCastRequest,
    SequenceEndEvent,
    SequenceType,
)
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from src.core.behaviors.behavior import Behavior
from src.core.behaviors.farms.fight.lua_fight_script_behavior import (
    CHALLENGE_PROPOSAL_TIMEOUT_SECONDS,
    CHALLENGE_SELECTION_TIMEOUT_SECONDS,
    SPELL_CAST_TIMEOUT_SECONDS,
    LuaFightScriptBehavior,
    LuaFightScriptError,
    LuaStarter,
)
from src.core.bot.bot import Bot
from src.core.engine.lua_fight.api import LuaFightApi
from src.core.engine.lua_fight.script import LuaFightScript
from tests.fixtures.game_state import set_game_state

PLAYER_CELL = 300
ENEMY_CELL = 302
SAFETY_TIMEOUTS = {
    SPELL_CAST_TIMEOUT_SECONDS,
    CHALLENGE_PROPOSAL_TIMEOUT_SECONDS,
    CHALLENGE_SELECTION_TIMEOUT_SECONDS,
}


class ManualTimers:
    def __init__(self) -> None:
        self.pending: list[tuple[float, Callable[[], None]]] = []

    def run_timer(self, behavior: Behavior, range_time: tuple[float, float] | float, func: Callable[[], None]):
        delay = range_time[0] if isinstance(range_time, tuple) else range_time
        self.pending.append((delay, lambda: behavior.run_timed_func(func)))

    def run_pauses(self) -> None:
        while due := [timer for timer in self.pending if timer[0] not in SAFETY_TIMEOUTS]:
            for timer in due:
                self.pending.remove(timer)
                timer[1]()

    def run_timeouts(self) -> None:
        due, self.pending = self.pending, []
        for _, func in due:
            func()


@pytest.fixture
def timers(monkeypatch: pytest.MonkeyPatch) -> ManualTimers:
    manual_timers = ManualTimers()
    def run_timer(behavior: Behavior, range_time: tuple[float, float] | float, func: Callable[[], None]) -> None:
        manual_timers.run_timer(behavior, range_time, func)

    monkeypatch.setattr(Behavior, "run_timer", run_timer)
    return manual_timers


@pytest.fixture
def sent_messages(runtime_bot: Bot) -> list[Message]:
    messages: list[Message] = []
    runtime_bot.event_manager.on_send_game_callback = messages.append
    return messages


def _fight_bot(runtime_bot: Bot) -> Bot:
    set_game_state(runtime_bot.game_state, player_cell_id=PLAYER_CELL, enemy_cell_ids=[ENEMY_CELL])
    runtime_bot.game_state.fight.is_our_turn = True
    return runtime_bot


def _script(bot: Bot, source: str) -> LuaFightScript:
    return LuaFightScript(
        source,
        "@test.lua",
        lambda to_lua: LuaFightApi(bot.game_state, bot.logger, to_lua).functions(),
    )


def _lua_behavior(bot: Bot) -> LuaFightScriptBehavior:
    return bot.fight_behavior.fight_turn_behavior.lua_fight_script_behavior


def _first_spell_name(bot: Bot) -> tuple[int, str]:
    spell_id = bot.game_state.fight.spells[0].spell_id
    return spell_id, I18N().name_by_id[DataReader().spell_by_id[spell_id].nameId]


ScriptResult = tuple[str | None, tuple[object, ...]]


def _start(bot: Bot, starter: LuaStarter) -> list[ScriptResult]:
    results: list[ScriptResult] = []

    def on_finished(error_code: str | None, values: tuple[object, ...]) -> None:
        results.append((error_code, values))

    _lua_behavior(bot).start(callback=on_finished, parent=None, start=starter)
    return results


class TestLuaFightScriptBehavior:
    def test_cast_resumes_after_the_server_ends_the_spell_then_passes_turn(
        self, runtime_bot: Bot, timers: ManualTimers, sent_messages: list[Message]
    ) -> None:
        bot = _fight_bot(runtime_bot)
        spell_id, spell_name = _first_spell_name(bot)
        script = _script(
            bot,
            f"""
            function main()
                RESULT = fight:CastSpell("{spell_name}", {ENEMY_CELL})
                fight:PassTurn()
            end
            """,
        )

        results = _start(bot, script.start_main)
        timers.run_pauses()
        assert sent_messages == [GameActionFightCastRequest(spell_id=spell_id, cell=ENEMY_CELL)]

        bot.event_manager.process_msg(
            SequenceEndEvent(author_id=bot.game_state.player.character_id, sequence_type=SequenceType.SPELL)
        )

        assert sent_messages[-1] == FightTurnFinishRequest()
        assert results == [(None, ())]
        assert _lua_behavior(bot).turn_passed

    def test_unanswered_cast_resumes_the_script_with_false(
        self, runtime_bot: Bot, timers: ManualTimers, sent_messages: list[Message]
    ) -> None:
        bot = _fight_bot(runtime_bot)
        _, spell_name = _first_spell_name(bot)
        script = _script(bot, f'function main() return fight:CastSpell("{spell_name}", {ENEMY_CELL}) end')

        results = _start(bot, script.start_main)
        timers.run_pauses()
        timers.run_timeouts()

        assert results == [(None, (False,))]

    def test_unknown_spell_name_is_not_sent(
        self, runtime_bot: Bot, timers: ManualTimers, sent_messages: list[Message]
    ) -> None:
        bot = _fight_bot(runtime_bot)
        script = _script(bot, f'function main() return fight:CastSpell("Not a spell", {ENEMY_CELL}) end')

        results = _start(bot, script.start_main)

        assert results == [(None, (False,))]
        assert sent_messages == []

    def test_script_error_is_reported_to_the_caller(self, runtime_bot: Bot, timers: ManualTimers) -> None:
        bot = _fight_bot(runtime_bot)
        script = _script(bot, "function main() fight:Delay(10); error('boom') end")

        results = _start(bot, script.start_main)
        timers.run_pauses()

        assert results == [(LuaFightScriptError.SCRIPT_FAILED, ())]

    def test_placement_requests_choice_and_selects_a_proposed_challenge(
        self, runtime_bot: Bot, timers: ManualTimers, sent_messages: list[Message]
    ) -> None:
        bot = _fight_bot(runtime_bot)
        script = _script(
            bot,
            """
            function fight:placement(possible, available)
                fight:RequestChallengeChoice()
                local ids = {}
                for _, challenge in pairs(fight:GetChallenges()) do
                    ids[#ids + 1] = fight:GetChallengeProperty(challenge, "challengeId")
                end
                SELECTED = fight:SelectChallenge(ids[2])
                return available[1]
            end
            """,
        )

        bot.game_state.fight.fight_placement_possible_positions = [100, 120]
        results = _start(bot, lambda: script.start_placement([100, 120], [120]))
        bot.event_manager.process_msg(
            ChallengeProposalEvent(challenge_proposals=[Challenge(challenge_id=8), Challenge(challenge_id=36)])
        )
        timers.run_pauses()
        bot.event_manager.process_msg(ChallengeSelectedEvent(challenge=Challenge(challenge_id=36)))

        assert sent_messages == [
            ChallengeModSelectRequest(),
            ChallengeReadyRequest(),
            ChallengeSelectionRequest(challenge_id=36),
        ]
        assert results == [(None, (120,))]
        assert bot.game_state.fight.selected_challenge_ids == [36]

    def test_challenge_absent_from_proposals_is_not_sent(
        self, runtime_bot: Bot, timers: ManualTimers, sent_messages: list[Message]
    ) -> None:
        bot = _fight_bot(runtime_bot)
        bot.event_manager.process_msg(ChallengeProposalEvent(challenge_proposals=[Challenge(challenge_id=8)]))
        script = _script(bot, "function fight:placement() return fight:SelectChallenge(99) end")

        results = _start(bot, lambda: script.start_placement([], []))

        assert results == [(None, (False,))]
        assert sent_messages == []


class TestLuaFightApi:
    def _api(self, bot: Bot) -> dict[str, Callable[..., Any]]:
        # Identity conversion keeps the returned tables as Python dicts and lists.
        return dict(LuaFightApi(bot.game_state, bot.logger, lambda value: value).functions())

    def test_fighters_exclude_the_player_and_split_teams(self, runtime_bot: Bot) -> None:
        api = self._api(_fight_bot(runtime_bot))

        enemies: dict[str, dict[str, object]] = api["GetAllEnnemyFighter"]()
        assert list(enemies) == ["0"]
        assert enemies["0"]["cellId"] == ENEMY_CELL
        assert api["GetAllAllyFighter"]() == {}
        assert api["IsEnemy"]("0") is True
        assert api["GetFighterIdOnCell"](ENEMY_CELL) == "0"
        assert api["GetFighterCell"]("404") == -1

    def test_challenge_state_tracks_list_targets_and_failure(self, runtime_bot: Bot) -> None:
        bot = _fight_bot(runtime_bot)
        api = self._api(bot)
        bot.event_manager.process_msg(
            ChallengeListEvent(
                challenges=[
                    Challenge(
                        challenge_id=32,
                        state=Challenge.CHALLENGE_RUNNING,
                        targets=[ChallengeTarget(target_id=0, target_cell=ENEMY_CELL)],
                    ),
                    Challenge(challenge_id=36, state=Challenge.CHALLENGE_RUNNING),
                ]
            )
        )
        bot.event_manager.process_msg(ChallengeResultEvent(challenge_id=36, success=False))

        challenges: list[dict[str, object]] = api["GetChallenges"]()
        assert {challenge["challengeId"]: challenge["state"] for challenge in challenges} == {
            32: "CHALLENGE_RUNNING",
            36: "CHALLENGE_FAILED",
        }
        assert api["IsChallengeValidate"](32) is True
        assert api["IsChallengeValidate"](36) is False
        assert api["GetChallengeTarget"](32) == {"targetId": "0", "targetCell": ENEMY_CELL}

    def test_spell_lookup_ignores_case_and_accents(self, runtime_bot: Bot) -> None:
        bot = _fight_bot(runtime_bot)
        spell_id, spell_name = _first_spell_name(bot)
        api = self._api(bot)

        assert api["GetSpellIdByName"](spell_name.upper()) == spell_id
        assert api["GetSpellIdByName"]("Not a spell") == 0
        assert api["CanCastSpell"]("Not a spell", ENEMY_CELL) is False

    def test_free_cells_exclude_occupied_cells(self, runtime_bot: Bot) -> None:
        bot = _fight_bot(runtime_bot)
        api = self._api(bot)

        free_cells: list[int] = api["GetFreeCellsAround"](PLAYER_CELL, 2)
        assert ENEMY_CELL not in free_cells
        assert PLAYER_CELL not in free_cells
        assert all(api["GetDistanceBetweenCells"](PLAYER_CELL, cell) <= 2 for cell in free_cells)
