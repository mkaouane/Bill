from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

from DBDofusUnity.datas.protos.non_obf.game.challenge_pb2 import (
    ChallengeModSelectRequest,
    ChallengeProposalEvent,
    ChallengeReadyRequest,
    ChallengeSelectedEvent,
    ChallengeSelectionRequest,
)
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ChallengeMod
from DBDofusUnity.datas.protos.non_obf.game.fight_pb2 import FightTurnFinishRequest
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint

from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.farms.fight.fight_listener_behavior import FightListenerBehavior
from src.core.behaviors.farms.fight.fight_movement_behavior import FightMovementBehavior
from src.core.behaviors.farms.fight.fight_spell_behavior import FightSpellBehavior
from src.core.behaviors.movements.map_move_behavior import MapMoveError
from src.core.engine.lua_fight.api import MAP_CELL_COUNT, find_own_spell, to_int
from src.core.engine.lua_fight.script import LuaAction, LuaCall, LuaFinished, LuaScriptError, LuaStep
from src.core.engine.movements.map.path_finding.movement_path import MovementPath
from src.services.human_timings import HumanTimingsService

SPELL_CAST_TIMEOUT_SECONDS = 5.0
CHALLENGE_PROPOSAL_TIMEOUT_SECONDS = 3.0
CHALLENGE_SELECTION_TIMEOUT_SECONDS = 3.0
MAX_DELAY_SECONDS = 10.0

LuaStarter = Callable[[], tuple[LuaCall, LuaStep]]
Resume = Callable[..., None]


class LuaFightScriptError:
    SCRIPT_FAILED = "LUA_SCRIPT_FAILED"


@dataclass
class LuaFightScriptBehavior(FightListenerBehavior):
    """Runs one entry point of a fight script, executing each yielded DoFarm action before resuming it.

    Finishes with the values returned by the script; `turn_passed` tells whether the script ended the turn.
    """

    fight_spell_behavior: FightSpellBehavior
    fight_movement_behavior: FightMovementBehavior

    turn_passed: bool = field(init=False, default=False)
    _call: LuaCall | None = field(init=False, default=None)
    _action_token: int = field(init=False, default=0)
    _resume_lock: Lock = field(init=False, default_factory=Lock)

    def run(self, start: LuaStarter) -> None:
        self.turn_passed = False
        self.register_fight_death_check()
        try:
            self._call, step = start()
        except LuaScriptError as error:
            return self._fail(error)
        self._handle_step(step)

    def clear_behavior(self) -> None:
        self._discard_call()
        super().clear_behavior()

    def _resumer(self) -> Resume:
        """Each action may resume the script once; late answers after a timeout are dropped."""
        with self._resume_lock:
            self._action_token += 1
            token = self._action_token

        def resume(*values: object) -> None:
            with self._resume_lock:
                if token != self._action_token:
                    return
                self._action_token += 1
            self._resume(*values)

        return resume

    def _resume(self, *values: object) -> None:
        if self.state != BehaviorState.RUNNING or self._call is None:
            return
        try:
            step = self._call.resume(*values)
        except LuaScriptError as error:
            return self._fail(error)
        self._handle_step(step)

    def _handle_step(self, step: LuaStep) -> None:
        if isinstance(step, LuaFinished):
            self._call = None
            return self.finish(None, step.values)
        handlers: dict[str, Callable[[LuaAction, Resume], None]] = {
            "CastSpell": self._cast_spell,
            "MoveToCell": self._move_to_cell,
            "MoveToClosestEnemy": self._move_to_closest_enemy,
            "Delay": self._delay,
            "PassTurn": self._pass_turn,
            "RequestChallengeChoice": self._request_challenge_choice,
            "SelectChallenge": self._select_challenge,
        }
        handler = handlers.get(step.name)
        if handler is None:
            return self._fail(LuaScriptError(f"Unsupported fight action {step.name}"))
        handler(step, self._resumer())

    def _fail(self, error: LuaScriptError) -> None:
        self.logger.error(f"[lua] Script error: {error}")
        self._discard_call()
        self.finish(LuaFightScriptError.SCRIPT_FAILED, ())

    def _discard_call(self) -> None:
        if self._call is not None:
            self._call.cancel()
            self._call = None

    @staticmethod
    def _arg(action: LuaAction, index: int) -> object:
        return action.args[index] if index < len(action.args) else None

    def _target_cell(self, value: object) -> int | None:
        cell = to_int(value)
        if not self.game_state.fight.is_our_turn or cell is None or not 0 <= cell < MAP_CELL_COUNT:
            return None
        return cell

    def _cast_spell(self, action: LuaAction, resume: Resume) -> None:
        own_spell = find_own_spell(self.game_state, self._arg(action, 0))
        cell = self._target_cell(self._arg(action, 1))
        if own_spell is None or cell is None:
            self.logger.info(f"[lua] CastSpell ignored: {action.args}")
            return resume(False)
        spell_id = own_spell.spell_id

        def on_cast_finished(error_code: str | None) -> None:
            if error_code is MapMoveError.PLAYER_DEAD:
                return self.finish(error_code, ())
            resume(error_code is None)

        def on_cast_timeout() -> None:
            if self.fight_spell_behavior.state == BehaviorState.RUNNING:
                self.logger.warning(f"[lua] No server answer to spell {spell_id} on cell {cell}")
                self.fight_spell_behavior.stop()
            resume(False)

        def start_cast() -> None:
            self.fight_spell_behavior.start(
                spell_id=spell_id,
                target_mp=MapPoint.from_cell_id(cell),
                parent=self,
                callback=on_cast_finished,
            )
            self.run_timer(SPELL_CAST_TIMEOUT_SECONDS, on_cast_timeout)

        self.run_timer(HumanTimingsService().get_timing_fight_action(False), start_cast)

    def _move_to_cell(self, action: LuaAction, resume: Resume) -> None:
        cell = self._target_cell(self._arg(action, 0))
        if cell is None:
            return resume(False)
        if cell == self.game_state.map.map_point.cell_id:
            return resume(True)
        self._move(self.fight_movement_behavior.find_path_to_cell(MapPoint.from_cell_id(cell)), resume)

    def _move_to_closest_enemy(self, action: LuaAction, resume: Resume) -> None:
        if not self.game_state.fight.is_our_turn:
            return resume(False)
        near_enemy = self.fight_movement_behavior.find_near_enemy_with_dist(self.game_state.map.map_point)
        if near_enemy is None:
            return resume(False)
        self._move(near_enemy[1], resume)

    def _move(self, move_path: MovementPath, resume: Resume) -> None:
        if not move_path.path:
            return resume(False)
        start_cell = self.game_state.map.map_point.cell_id

        def on_moved(error_code: str | None, cell_mp: MapPoint | None = None) -> None:
            if error_code is MapMoveError.PLAYER_DEAD:
                return self.finish(error_code, ())
            if error_code is MapMoveError.CELL_TAKEN and cell_mp is not None:
                self.game_state.fight.add_invisible_enemy_cell(cell_mp.cell_id)
            resume(self.game_state.map.map_point.cell_id != start_cell)

        self.run_timer(
            HumanTimingsService().get_timing_fight_action(False),
            lambda: self.fight_movement_behavior.start(callback=on_moved, parent=self, move_path=move_path),
        )

    def _delay(self, action: LuaAction, resume: Resume) -> None:
        milliseconds = to_int(self._arg(action, 0)) or 0
        self.run_timer(min(max(milliseconds, 0) / 1000, MAX_DELAY_SECONDS), resume)

    def _pass_turn(self, action: LuaAction, resume: Resume) -> None:
        self._discard_call()
        if self.game_state.fight.is_our_turn:
            self.turn_passed = True
            self.event_manager.send(FightTurnFinishRequest())
        self.finish(None, ())

    def _request_challenge_choice(self, action: LuaAction, resume: Resume) -> None:
        if self.game_state.fight.challenge_proposals:
            return resume(True)
        self.event_manager.on(ChallengeProposalEvent, lambda _msg: resume(True), originator=self, once=True)
        # Socket mode already asks for a choice in the session behavior; a MITM client may be in random mode.
        if not self.event_manager.is_socket_mode:
            self.event_manager.send(ChallengeModSelectRequest(challenge_mod=ChallengeMod.CHALLENGE_CHOICE))
            self.event_manager.send(ChallengeReadyRequest(challenge_mod=ChallengeMod.CHALLENGE_CHOICE))
        self.run_timer(CHALLENGE_PROPOSAL_TIMEOUT_SECONDS, lambda: resume(False))

    def _select_challenge(self, action: LuaAction, resume: Resume) -> None:
        challenge_id = to_int(self._arg(action, 0))
        proposal_ids = {proposal.challenge_id for proposal in self.game_state.fight.challenge_proposals}
        if challenge_id is None or challenge_id not in proposal_ids:
            self.logger.info(f"[lua] Challenge {challenge_id} is not among proposals {sorted(proposal_ids)}")
            return resume(False)
        self.event_manager.on(
            ChallengeSelectedEvent,
            lambda msg: resume(msg.challenge.challenge_id == challenge_id),
            originator=self,
            once=True,
        )
        self.send_message_delayed(
            ChallengeSelectionRequest(challenge_id=challenge_id),
            HumanTimingsService().get_timing_fight_challenge_selection(),
        )
        self.run_timer(CHALLENGE_SELECTION_TIMEOUT_SECONDS, lambda: resume(False))
