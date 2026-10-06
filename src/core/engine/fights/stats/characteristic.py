from collections.abc import Mapping

from DBDofusUnity.datas.protos.non_obf.game.character_pb2 import (
    CharacterCharacteristicUpgradeRequest,
)
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    CharacterCharacteristic,
)
from DBDofusUnity.dofus_unity_reader.game_constants.characteristic import CharacteristicEnum, EffectElement


def get_stat_by_id(stat: CharacterCharacteristic | None) -> int:
    if stat is None:
        return 0
    if stat.HasField("detailed"):
        return (
            stat.detailed.base
            + stat.detailed.additional
            + stat.detailed.objects_and_mount_bonus
            + stat.detailed.alignment_gift_bonus
            + stat.detailed.context_modification
            + stat.detailed.temporary
        )
    elif stat.HasField("usable"):
        return (
            stat.usable.base
            + stat.usable.objects_and_mount_bonus
            + stat.usable.alignment_gift_bonus
            + stat.usable.additional
            + stat.usable.context_modification
            + stat.usable.temporary
        )
    elif stat.HasField("value"):
        return stat.value.total

    return 0


# The upgrade request carries absolute base values: any omitted characteristic is reset to 0.
UPGRADABLE_CHARACTERISTIC_BY_FIELD: dict[str, CharacteristicEnum] = {
    "strength": CharacteristicEnum.STRENGTH,
    "vitality": CharacteristicEnum.VITALITY,
    "wisdom": CharacteristicEnum.WISDOM,
    "chance": CharacteristicEnum.CHANCE,
    "agility": CharacteristicEnum.AGILITY,
    "intelligence": CharacteristicEnum.INTELLIGENCE,
}

ELEMENT_UPGRADE_FIELD: dict[EffectElement, str] = {
    EffectElement.STRENGTH: "strength",
    EffectElement.INTELLIGENCE: "intelligence",
    EffectElement.CHANCE: "chance",
    EffectElement.AGILITY: "agility",
}


def get_base_stat(stat: CharacterCharacteristic) -> int:
    if stat.HasField("detailed"):
        return stat.detailed.base
    if stat.HasField("usable"):
        return stat.usable.base
    return stat.value.total


def get_characteristic_point_cost(base: int) -> int:
    return min(base // 100 + 1, 4)


def spend_characteristic_points(base: int, points: int) -> int:
    while points >= (cost := get_characteristic_point_cost(base)):
        points -= cost
        base += 1
    return base


def build_characteristic_upgrade_request(
    primary_element: EffectElement,
    characteristic_by_id: Mapping[int, CharacterCharacteristic],
) -> CharacterCharacteristicUpgradeRequest | None:
    """Keeps the current distribution and spends the unspent points on the primary element."""
    stats_points = characteristic_by_id.get(CharacteristicEnum.STATS_POINTS)
    if stats_points is None or any(
        characteristic_id not in characteristic_by_id
        for characteristic_id in UPGRADABLE_CHARACTERISTIC_BY_FIELD.values()
    ):
        return None
    base_by_field = {
        field: get_base_stat(characteristic_by_id[characteristic_id])
        for field, characteristic_id in UPGRADABLE_CHARACTERISTIC_BY_FIELD.items()
    }
    field = ELEMENT_UPGRADE_FIELD.get(primary_element, "agility")
    upgraded_base = spend_characteristic_points(base_by_field[field], get_stat_by_id(stats_points))
    if upgraded_base == base_by_field[field]:
        return None
    base_by_field[field] = upgraded_base
    return CharacterCharacteristicUpgradeRequest(**base_by_field)
