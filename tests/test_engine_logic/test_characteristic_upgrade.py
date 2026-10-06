from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    CharacterCharacteristic,
    CharacterCharacteristicDetailed,
    CharacterCharacteristicValue,
)
from DBDofusUnity.dofus_unity_reader.game_constants.characteristic import CharacteristicEnum, EffectElement

from src.core.engine.fights.stats.characteristic import build_characteristic_upgrade_request


def _characteristics(stats_points: int, **base_by_field: int) -> dict[int, CharacterCharacteristic]:
    bases = {
        CharacteristicEnum.STRENGTH: base_by_field.get("strength", 0),
        CharacteristicEnum.VITALITY: base_by_field.get("vitality", 0),
        CharacteristicEnum.WISDOM: base_by_field.get("wisdom", 0),
        CharacteristicEnum.CHANCE: base_by_field.get("chance", 0),
        CharacteristicEnum.AGILITY: base_by_field.get("agility", 0),
        CharacteristicEnum.INTELLIGENCE: base_by_field.get("intelligence", 0),
    }
    characteristics: dict[int, CharacterCharacteristic] = {
        characteristic_id: CharacterCharacteristic(
            characteristic_id=characteristic_id,
            detailed=CharacterCharacteristicDetailed(base=base, objects_and_mount_bonus=50),
        )
        for characteristic_id, base in bases.items()
    }
    characteristics[CharacteristicEnum.STATS_POINTS] = CharacterCharacteristic(
        characteristic_id=CharacteristicEnum.STATS_POINTS,
        value=CharacterCharacteristicValue(total=stats_points),
    )
    return characteristics


def test_level_up_keeps_existing_distribution_and_adds_points_to_primary_element() -> None:
    characteristics = _characteristics(5, strength=40, vitality=30, wisdom=10, agility=7)

    request = build_characteristic_upgrade_request(EffectElement.STRENGTH, characteristics)

    assert request is not None
    assert (request.strength, request.vitality, request.wisdom, request.agility) == (45, 30, 10, 7)
    assert (request.chance, request.intelligence) == (0, 0)


def test_points_follow_the_increasing_cost_tiers() -> None:
    request = build_characteristic_upgrade_request(EffectElement.CHANCE, _characteristics(10, chance=98))

    assert request is not None
    # 2 points reach 100, the remaining 8 buy 4 points at cost 2.
    assert request.chance == 104


def test_no_request_without_points_or_complete_characteristics() -> None:
    assert build_characteristic_upgrade_request(EffectElement.AGILITY, _characteristics(0, agility=50)) is None

    incomplete = _characteristics(5, agility=50)
    del incomplete[CharacteristicEnum.WISDOM]
    assert build_characteristic_upgrade_request(EffectElement.AGILITY, incomplete) is None
