import logging

import pytest
from pydantic import ValidationError

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ActorPositionInformation, EntityDisposition
from DBDofusUnity.dofus_unity_reader.game_constants.monster import MonsterGidEnum

from src.core.behaviors.farms.fight.attacker_behavior import AttackerBehavior
from src.core.bot.bot import Bot
from src.core.config import MAX_MONSTER_GROUP_SIZE, BehaviorSettings
from src.core.engine.monsters.monster_group import get_monster_group_gids, is_group_targetable
from tests.fixtures.game_state import set_game_state

MonsterGroupActor = ActorPositionInformation.ActorInformation.RolePlayActor.MonsterGroupActor

XELOR_LOUCHE_MONSTER_ID = 3363
TOFU_MONSTER_ID = 98

_LOGGER = logging.getLogger(__name__)


def _make_monster_group(main_gid: int, underling_gids: list[int]) -> MonsterGroupActor:
    monster_group = MonsterGroupActor()
    monster_group.identification.main_creature.gid = main_gid
    for gid in underling_gids:
        monster_group.identification.underlings.add().gid = gid
    return monster_group


def test_group_gids_include_main_creature_and_underlings() -> None:
    monster_group = _make_monster_group(XELOR_LOUCHE_MONSTER_ID, [TOFU_MONSTER_ID, TOFU_MONSTER_ID])

    assert get_monster_group_gids(monster_group) == {XELOR_LOUCHE_MONSTER_ID, TOFU_MONSTER_ID}


def test_targeting_matches_when_the_quest_monster_is_an_underling() -> None:
    monster_group = _make_monster_group(TOFU_MONSTER_ID, [XELOR_LOUCHE_MONSTER_ID])

    assert {XELOR_LOUCHE_MONSTER_ID} & get_monster_group_gids(monster_group)


def test_is_group_targetable_rejects_forbidden_gid() -> None:
    monster_group = _make_monster_group(MonsterGidEnum.POUTCH, [])

    assert not is_group_targetable(_LOGGER, monster_group, 10, lvl_limit=100, monster_ids=None)


def test_is_group_targetable_rejects_when_monster_ids_do_not_match() -> None:
    monster_group = _make_monster_group(TOFU_MONSTER_ID, [])

    assert not is_group_targetable(
        _LOGGER,
        monster_group,
        10,
        lvl_limit=100,
        monster_ids={XELOR_LOUCHE_MONSTER_ID},
    )


def test_is_group_targetable_accepts_when_monster_ids_match() -> None:
    monster_group = _make_monster_group(XELOR_LOUCHE_MONSTER_ID, [])

    assert is_group_targetable(
        _LOGGER,
        monster_group,
        10,
        lvl_limit=100,
        monster_ids={XELOR_LOUCHE_MONSTER_ID},
    )


def test_is_group_targetable_rejects_group_over_lvl_limit() -> None:
    monster_group = _make_monster_group(TOFU_MONSTER_ID, [])

    assert not is_group_targetable(_LOGGER, monster_group, 150, lvl_limit=100, monster_ids=None)


def test_is_group_targetable_accepts_group_within_lvl_limit() -> None:
    monster_group = _make_monster_group(TOFU_MONSTER_ID, [])

    assert is_group_targetable(_LOGGER, monster_group, 100, lvl_limit=100, monster_ids=None)


def test_is_group_targetable_keeps_groups_inside_the_size_range() -> None:
    four_monsters = _make_monster_group(TOFU_MONSTER_ID, [TOFU_MONSTER_ID] * 3)
    three_monsters = _make_monster_group(TOFU_MONSTER_ID, [TOFU_MONSTER_ID] * 2)

    assert is_group_targetable(_LOGGER, four_monsters, 10, lvl_limit=100, monster_ids=None, size_range=(4, 8))
    assert not is_group_targetable(
        _LOGGER, three_monsters, 10, lvl_limit=100, monster_ids=None, size_range=(4, 8)
    )
    assert not is_group_targetable(
        _LOGGER, four_monsters, 10, lvl_limit=100, monster_ids=None, size_range=(1, 3)
    )


def _add_monster_group(bot: Bot, actor_id: int, cell_id: int, size: int) -> None:
    actor = ActorPositionInformation(
        actor_id=actor_id,
        disposition=EntityDisposition(cell_id=cell_id, entity_id=actor_id),
    )
    actor.actor_information.role_play_actor.monster_group_actor.CopyFrom(
        _make_monster_group(TOFU_MONSTER_ID, [TOFU_MONSTER_ID] * (size - 1))
    )
    bot.game_state.entity.set_actor(actor)


SMALL_GROUP_ID = -100
BIG_GROUP_ID = -101


def _bot_with_small_and_big_groups(runtime_bot: Bot, min_size: int, max_size: int) -> AttackerBehavior:
    set_game_state(runtime_bot.game_state, player_cell_id=300, enemy_cell_ids=[])
    _add_monster_group(runtime_bot, SMALL_GROUP_ID, 302, size=2)
    _add_monster_group(runtime_bot, BIG_GROUP_ID, 328, size=6)
    runtime_bot.game_state.apply_settings(
        BehaviorSettings(fight_group_min_size=min_size, fight_group_max_size=max_size)
    )
    return runtime_bot.fighter_behavior.attacker_behavior


def test_attacker_only_picks_groups_inside_the_configured_size_range(runtime_bot: Bot) -> None:
    attacker = _bot_with_small_and_big_groups(runtime_bot, min_size=4, max_size=8)

    for _ in range(10):
        next_enemy = attacker.get_next_enemy()
        assert next_enemy is not None
        assert next_enemy.actor_id == BIG_GROUP_ID


def test_attacker_finds_nothing_when_no_group_fits_the_size_range(runtime_bot: Bot) -> None:
    attacker = _bot_with_small_and_big_groups(runtime_bot, min_size=7, max_size=8)

    assert attacker.get_next_enemy() is None


def test_dungeon_fights_ignore_the_size_range(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    attacker = _bot_with_small_and_big_groups(runtime_bot, min_size=7, max_size=8)
    def skip_attack(excluded_group_actor_id: int | None = None) -> None:
        del excluded_group_actor_id

    monkeypatch.setattr(attacker, "attack_enemy", skip_attack)

    attacker.run(respect_group_size=False)

    assert attacker.get_next_enemy() is not None


def test_settings_reject_an_inverted_or_out_of_bounds_size_range() -> None:
    with pytest.raises(ValidationError):
        BehaviorSettings(fight_group_min_size=5, fight_group_max_size=4)
    with pytest.raises(ValidationError):
        BehaviorSettings(fight_group_max_size=MAX_MONSTER_GROUP_SIZE + 1)
    assert BehaviorSettings().fight_group_min_size == 1
    assert BehaviorSettings().fight_group_max_size == MAX_MONSTER_GROUP_SIZE
