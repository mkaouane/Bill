from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItemInventory

from src.consts import FAKE_INFINITY_VALUE
from src.core.config import JobPrioritySettings
from src.core.engine.weights.harvester.weight_collectable import (
    get_map_id_collectable_weight,
)


def get_harvester_additional_weight_by_map_id(
    map_id: int,
    map_ids_to_explore: set[int],
    jobs_lvl_by_id: dict[int, int],
    storage_by_gid: dict[int, ObjectItemInventory],
    is_sub: bool,
    job_priorities: JobPrioritySettings,
    server_id: int,
):
    if map_id in map_ids_to_explore:
        return FAKE_INFINITY_VALUE
    weight = get_map_id_collectable_weight(
        map_id,
        jobs_lvl_by_id,
        storage_by_gid,
        is_sub,
        job_priorities,
        server_id,
    )
    return weight
