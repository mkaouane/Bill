import datetime
from random import uniform

from dotenv import load_dotenv
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from DBDofusUnity.dofus_unity_reader.game_constants.job import JobEnum
from DBDofusUnity.dofus_unity_reader.game_constants.map_id import MapIdEnum
from src.utils.project_paths import ENV_PATH, IS_PACKAGED
from utils.env_config import get_bool_from_env

load_dotenv(ENV_PATH)
DEBUG = get_bool_from_env("DEBUG", default=True)
ENABLE_MSG_CAPTURE = not IS_PACKAGED

ENABLE_SESSION_CONTEXT = False


MAX_MONSTER_GROUP_SIZE = 8


JobPriority = Literal["ignored", "normal", "priority"]

JOB_PRIORITY_WEIGHT_MULTIPLIER: dict[JobPriority, float] = {
    "ignored": 0,
    "normal": 1,
    "priority": 10,
}


class JobPrioritySettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    woodcutter: JobPriority = "normal"
    miner: JobPriority = "normal"
    alchemist: JobPriority = "normal"
    peasant: JobPriority = "normal"
    fisherman: JobPriority = "normal"

    def priority_of(self, job_id: int) -> JobPriority:
        match job_id:
            case JobEnum.WOODCUTTER:
                return self.woodcutter
            case JobEnum.MINER:
                return self.miner
            case JobEnum.ALCHEMIST:
                return self.alchemist
            case JobEnum.PEASANT:
                return self.peasant
            case JobEnum.FISHERMAN:
                return self.fisherman
            case _:
                return "normal"

    def weight_multiplier(self, job_id: int) -> float:
        return JOB_PRIORITY_WEIGHT_MULTIPLIER[self.priority_of(job_id)]

    def is_ignored(self, job_id: int) -> bool:
        return self.priority_of(job_id) == "ignored"


class BehaviorSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    do_fighter: bool = True
    do_sale_hotel: bool = True
    do_craft: bool = False
    do_use_guild_chest: bool = False
    do_dungeon: bool = False
    do_idle: bool = False
    enable_auto_equipment_market_purchases: bool = False
    enable_auto_ogrine_subscriptions: bool = False
    enable_auto_paysafecard_subscriptions: bool = False
    fight_group_min_size: int = Field(default=1, ge=1, le=MAX_MONSTER_GROUP_SIZE)
    fight_group_max_size: int = Field(default=MAX_MONSTER_GROUP_SIZE, ge=1, le=MAX_MONSTER_GROUP_SIZE)
    job_priorities: JobPrioritySettings = JobPrioritySettings()

    @model_validator(mode="after")
    def check_fight_group_size_range(self) -> Self:
        if self.fight_group_min_size > self.fight_group_max_size:
            raise ValueError("The minimum monster group size cannot exceed the maximum.")
        return self


class GlobalSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    behaviors: BehaviorSettings = BehaviorSettings()
    enable_account_automation: bool = False
    sonji_api_key: str | None = None


FIGHT_GROUP_LVL_MULTIPLIER = 2
FIGHT_GROUP_LVL_OFFSET = 5


def get_default_fight_group_lvl_limit(level: int) -> float:
    return level * FIGHT_GROUP_LVL_MULTIPLIER + FIGHT_GROUP_LVL_OFFSET


USEFUL_UNLOAD = 0.15

OCCUPIED_MESSAGE_ID: int = 474
OCCUPIED_STUCK_LIMIT = 2

BOT_MINIMAL_KAMAS: int = 2_000_000
MULE_BANK_MAP_ID = MapIdEnum.ASTRUB_BANK

MAX_QUANTITY_ON_SELL = 10_000
MIN_KAMAS_TO_GO_SALE_HOTEL = 1_500


def get_time_beween_sale_hotel_prices():
    return datetime.timedelta(hours=4, minutes=0) * uniform(0.75, 1.25)


def get_time_beween_areas():
    return datetime.timedelta(hours=1) * uniform(0.75, 1.25)


def get_time_between_attacker(enabled: bool) -> datetime.timedelta:
    return (
        datetime.timedelta(minutes=20) * uniform(0.75, 1.25)
        if enabled
        else datetime.timedelta(datetime.MAXYEAR)
    )


WEIGHT_BY_JOB: dict[JobEnum, float] = {
    JobEnum.MINER: 5,
    JobEnum.WOODCUTTER: 5,
    JobEnum.ALCHEMIST: 5,
    JobEnum.FISHERMAN: 5,
    JobEnum.PEASANT: 2.5,
    JobEnum.BASE: 1,
}


BETWEEN_COLLECT_PAUSE_PROBABILITY = 0.1
FIRST_COLLECT_MOVEMENT_CANCEL_PROBABILITY = 1 / 3
SUBSEQUENT_COLLECT_MOVEMENT_CANCEL_PROBABILITY = 1 / 8
STATIC_INTERACTION_CANCEL_PROBABILITY = 1 / 8

PLACEMENT_REPOSITIONING_PROBABILITY = 0.08
PLACEMENT_NON_OPTIMAL_MOVE_PROBABILITY = 0.1
