from types import SimpleNamespace

import pytest
from DBDofusUnity.dofus_unity_reader.game_constants.job import JobEnum

from src.core.config import JobPrioritySettings
from src.core.engine.weights.harvester import weight_collectable


def _avg_price_by_gid(_server_id: int) -> dict[int, float]:
    return {100: 50.0, 200: 0.0}


def _rare_drop_weight_by_gid() -> dict[int, float]:
    return {}


def _basic_weight(*_args: object) -> float:
    return 10.0


@pytest.fixture(autouse=True)
def stub_game_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        weight_collectable, "GameDataController", lambda: SimpleNamespace(get_avg_price_by_gid=_avg_price_by_gid)
    )
    monkeypatch.setattr(weight_collectable, "get_rare_drop_weight_by_collectable_gid", _rare_drop_weight_by_gid)
    monkeypatch.setattr(weight_collectable, "get_basic_weight_collectable", _basic_weight)


def _weight(job_priorities: JobPrioritySettings, item_gid: int = 100) -> float:
    return weight_collectable.get_weight_collectable(
        JobEnum.FISHERMAN, 100, item_gid, {}, True, job_priorities
    )


def test_ignored_job_resources_have_no_weight() -> None:
    ignored = JobPrioritySettings(fisherman="ignored")

    assert _weight(ignored) == 0
    assert _weight(ignored, item_gid=200) == 0


def test_priority_job_resources_outweigh_normal_ones() -> None:
    assert _weight(JobPrioritySettings(fisherman="priority")) > _weight(JobPrioritySettings()) > 0


def test_other_job_priorities_do_not_change_weight() -> None:
    assert _weight(JobPrioritySettings(miner="ignored", woodcutter="priority")) == _weight(JobPrioritySettings())
