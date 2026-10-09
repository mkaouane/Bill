import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    ActorPositionInformation,
    Challenge,
    SpellModifierType,
)
from DBDofusUnity.datas.protos.non_obf.game.spell_pb2 import SpellItem
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from DBDofusUnity.dofus_unity_reader.data_center.map_reader import MapReader
from DBDofusUnity.dofus_unity_reader.game_constants.characteristic import CharacteristicEnum
from DBDofusUnity.dofus_unity_reader.game_constants.directions import DirectionsEnum
from DBDofusUnity.dofus_unity_reader.game_constants.spell_shape_enum import SpellShapeEnum
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from DBDofusUnity.dofus_unity_reader.models.datas.spell_levels_root import SpellLevelsRootItem
from src.core.engine.fights.attack.cast_validator import can_cast_spell_on_mp
from src.core.engine.fights.attack.positions import get_positions
from src.core.engine.fights.attack.spell_filter import resolve_castable_spell_lvl
from src.core.engine.fights.los_detector import LosDetector
from src.core.engine.fights.spell import does_spell_need_taken_cell, get_possible_mp_spell
from src.core.engine.fights.spell_modifier import SpellModifiers
from src.core.engine.fights.spell_zone import get_zone_mps
from src.core.engine.lua_fight.script import ToLua
from src.core.states.game_state import GameState
from src.services.logging_utils.loggers import BotLogger

MAP_CELL_COUNT = 560


def normalize_spell_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str | bytes):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def find_own_spell(game_state: GameState, spell: object) -> SpellItem | None:
    """Resolve a script spell reference, given as a spell id or an in-game name, among the player's spells."""
    spell_id = to_int(spell)
    wanted = None if spell_id is not None else normalize_spell_name(str(spell))
    for own_spell in list(game_state.fight.spells):
        if not own_spell.spell_id:
            continue
        if spell_id is not None:
            if own_spell.spell_id == spell_id:
                return own_spell
            continue
        name_id = DataReader().spell_by_id[own_spell.spell_id].nameId
        if normalize_spell_name(I18N().name_by_id.get(name_id, "")) == wanted:
            return own_spell
    return None


def _is_cell(cell_id: int | None) -> bool:
    return cell_id is not None and 0 <= cell_id < MAP_CELL_COUNT


class LuaFightApi:
    """DoFarm `fight:` functions that only read the game state; actions are handled by the script behavior."""

    def __init__(self, game_state: GameState, logger: BotLogger, to_lua: ToLua) -> None:
        self.game_state = game_state
        self.logger = logger
        self.to_lua = to_lua

    def functions(self) -> Mapping[str, Callable[..., object]]:
        return {
            "SendLogs": self.send_logs,
            "IsMyTurn": lambda: self.game_state.fight.is_our_turn,
            "GetTurnCount": lambda: self.game_state.fight.turn_in_current_fight,
            "GetMyCharacterId": lambda: str(self.game_state.player.character_id),
            "GetMyCell": lambda: self.game_state.map.map_point.cell_id,
            "GetPA": lambda: self.game_state.fight.get_stat_by_id(CharacteristicEnum.ACTION_POINTS),
            "GetPM": lambda: self.game_state.fight.get_stat_by_id(CharacteristicEnum.MOVEMENT_POINTS),
            "GetDistanceBetweenCells": self.get_distance_between_cells,
            "GetAllEnnemyFighter": lambda: self.to_lua(self._fighters_by_id(enemies=True)),
            "GetAllAllyFighter": lambda: self.to_lua(self._fighters_by_id(enemies=False)),
            "PlacementGetAllEnnemyFighter": lambda: self.to_lua(self._fighters_by_id(enemies=True)),
            "PlacementGetAllAllyFighter": lambda: self.to_lua(self._fighters_by_id(enemies=False)),
            "GetFighterCell": self.get_fighter_cell,
            "GetFighterLife": self.get_fighter_life,
            "GetFighterIdOnCell": self.get_fighter_id_on_cell,
            "IsEnemy": self.is_enemy,
            "GetStat": self.get_stat,
            "GetSpellIdByName": self.get_spell_id_by_name,
            "GetSpellCost": self.get_spell_cost,
            "CanCastSpell": self.can_cast_spell,
            "GetZoneCells": self.get_zone_cells,
            "GetFreeCellsAround": self.get_free_cells_around,
            "IsCellWalkable": self.is_cell_walkable,
            "HasLineOfSight": self.has_line_of_sight,
            "GetChallenges": self.get_challenges,
            "GetSelectedChallenge": self.get_selected_challenge,
            "IsChallengeValidate": self.is_challenge_validate,
            "GetChallengeTarget": self.get_challenge_target,
        }

    def send_logs(self, message: object, color: object = None) -> None:
        self.logger.info(f"[lua] {message}")

    def get_distance_between_cells(self, cell_a: object, cell_b: object) -> int:
        start, end = to_int(cell_a), to_int(cell_b)
        if not _is_cell(start) or not _is_cell(end):
            return -1
        assert start is not None and end is not None
        return int(MapPoint.from_cell_id(start).distance_to_map_point(MapPoint.from_cell_id(end)))

    def get_fighter_cell(self, fighter_id: object) -> int:
        actor = self._actor(fighter_id)
        return -1 if actor is None else actor.disposition.cell_id

    def get_fighter_life(self, fighter_id: object) -> int:
        actor_id = to_int(fighter_id)
        if actor_id == self.game_state.player.character_id:
            return self.game_state.fight.life_point
        if actor_id is None or self._actor(actor_id) is None:
            return 0
        fight_actor = self.game_state.entity.actor_fight_by_id.get(actor_id)
        return 0 if fight_actor is None else fight_actor.life_point

    def get_fighter_id_on_cell(self, cell_id: object) -> str:
        cell = to_int(cell_id)
        if not _is_cell(cell):
            return ""
        for actor in dict(self.game_state.entity.actor_by_id).values():
            if actor.disposition.cell_id == cell and actor.actor_information.HasField("fighter"):
                if self.get_fighter_life(actor.actor_id) > 0:
                    return str(actor.actor_id)
        return ""

    def is_enemy(self, fighter_id: object) -> bool:
        actor = self._actor(fighter_id)
        player = self._actor(self.game_state.player.character_id)
        if actor is None or player is None:
            return False
        return self._team(actor) != self._team(player)

    def get_stat(self, stat_name: object, fighter_id: object = None) -> int | None:
        actor_id = self.game_state.player.character_id if fighter_id is None else to_int(fighter_id)
        name = str(stat_name).casefold()
        if name in {"life", "lifepoints", "hp"}:
            return self.get_fighter_life(actor_id)
        if actor_id == self.game_state.player.character_id:
            stat_by_name = {
                "level": self.game_state.player.level,
                "pa": self.game_state.fight.get_stat_by_id(CharacteristicEnum.ACTION_POINTS),
                "pm": self.game_state.fight.get_stat_by_id(CharacteristicEnum.MOVEMENT_POINTS),
                "maxlife": self.game_state.fight.max_life_point,
                "range": self.game_state.fight.get_stat_by_id(CharacteristicEnum.RANGE),
            }
            return stat_by_name.get(name)
        actor = self._actor(actor_id)
        if actor is None or not actor.actor_information.fighter.HasField("ai_fighter"):
            return None
        monster_info = actor.actor_information.fighter.ai_fighter.monster_fighter_information
        monster = DataReader().monsters_by_id.get(monster_info.monster_gid)
        if monster is None or not 0 < monster_info.creature_grade <= len(monster.grades):
            return None
        grade = monster.grades[monster_info.creature_grade - 1]
        return {"level": grade.level, "maxlife": grade.lifePoints}.get(name)

    def get_spell_id_by_name(self, spell_name: object) -> int:
        spell_lvl = self._own_spell_lvl(spell_name)
        return 0 if spell_lvl is None else spell_lvl.spellId

    def get_spell_cost(self, spell_name: object) -> int | None:
        spell_lvl = self._own_spell_lvl(spell_name)
        if spell_lvl is None:
            return None
        modifiers = SpellModifiers.from_spell(
            self.game_state.fight.get_stat_by_id(CharacteristicEnum.RANGE),
            spell_lvl,
            self.game_state.fight.modifier_by_type_and_spell_id,
        )
        return modifiers.ap_cost

    def can_cast_spell(self, spell_name: object, cell_id: object) -> bool:
        cell = to_int(cell_id)
        spell_lvl = self._own_spell_lvl(spell_name)
        context = self.game_state.get_attack_context_if_available()
        if not _is_cell(cell) or spell_lvl is None or context is None:
            return False
        assert cell is not None
        castable_spell_lvl = resolve_castable_spell_lvl(context, spell_lvl.spellId)
        if castable_spell_lvl is None:
            return False
        modifiers_map = context.modifier_by_type_and_spell_id
        modifiers = SpellModifiers.from_spell(context.range, castable_spell_lvl, modifiers_map)
        target = MapPoint.from_cell_id(cell)
        spell_id = castable_spell_lvl.spellId
        in_range = get_possible_mp_spell(
            context.player_map_point,
            castable_spell_lvl,
            context.range,
            modifier_range_min=modifiers_map.get((spell_id, SpellModifierType.RANGE_MIN)),
            modifier_range_max=modifiers_map.get((spell_id, SpellModifierType.RANGE_MAX)),
            modifier_cast_line=modifiers_map.get((spell_id, SpellModifierType.CAST_LINE)),
        )
        if target not in in_range:
            return False
        positions = get_positions(context)
        if does_spell_need_taken_cell(castable_spell_lvl) and target not in positions.entities_mp:
            return False
        return can_cast_spell_on_mp(
            context,
            context.player_map_point,
            castable_spell_lvl,
            target,
            modifiers,
            positions.entities_mp,
            positions.entities_id_by_mp,
            defaultdict(int),
        )

    def get_zone_cells(self, spell_id: object, center_cell: object) -> object:
        center = to_int(center_cell)
        spell_lvl = self._spell_lvl_by_id(to_int(spell_id))
        if not _is_cell(center) or spell_lvl is None or not spell_lvl.effects:
            return self.to_lua([])
        assert center is not None
        effect = spell_lvl.effects[0]
        caster = self.game_state.map.map_point
        target = MapPoint.from_cell_id(center)
        zone = get_zone_mps(
            shape=SpellShapeEnum(effect.zoneDescr.shape),
            size=effect.zoneDescr.param1,
            alternative_size=effect.zoneDescr.param2,
            caster_mp=caster,
            stop_at_target=bool(effect.zoneDescr.isStopAtTarget),
        )
        direction = DirectionsEnum.DOWN_RIGHT if caster == target else caster.orientation_to(target)
        return self.to_lua(sorted(mp.cell_id for mp in zone.get_mps(mp=target, direction=direction)))

    def get_free_cells_around(self, center_cell: object, radius: object) -> object:
        center, max_distance = to_int(center_cell), to_int(radius)
        if not _is_cell(center) or max_distance is None or max_distance <= 0:
            return self.to_lua([])
        assert center is not None
        center_mp = MapPoint.from_cell_id(center)
        cells = [
            cell
            for cell in range(MAP_CELL_COUNT)
            if 0 < center_mp.distance_to_map_point(MapPoint.from_cell_id(cell)) <= max_distance
            and self.is_cell_walkable(cell)
        ]
        return self.to_lua(cells)

    def is_cell_walkable(self, cell_id: object) -> bool:
        cell = to_int(cell_id)
        if not _is_cell(cell):
            return False
        assert cell is not None
        cell_data = MapReader().get_cell_data_by_cell_id(self.game_state.map.map_id, cell)
        if not cell_data.movDuringFight:
            return False
        if cell in self.game_state.fight.invisible_enemy_cell_ids:
            return False
        return not self.game_state.entity.actors_on_mp.is_entity_actor_on_cell_id(cell)

    def has_line_of_sight(self, from_cell: object, to_cell: object) -> bool:
        start, end = to_int(from_cell), to_int(to_cell)
        if not _is_cell(start) or not _is_cell(end):
            return False
        assert start is not None and end is not None
        taken_mps = {
            MapPoint.from_cell_id(actor.disposition.cell_id)
            for actor in dict(self.game_state.entity.actor_by_id).values()
            if actor.disposition.cell_id not in {-1, start, end}
        }
        return LosDetector.los_between(
            map_id=self.game_state.map.map_id,
            taken_mps=taken_mps,
            start=MapPoint.from_cell_id(start),
            end=MapPoint.from_cell_id(end),
        )

    def get_challenges(self) -> object:
        fight = self.game_state.fight
        # Proposals only matter while placing; once turns start the script reads the fight's challenges.
        in_placement = bool(fight.fight_placement_possible_positions)
        challenges = (
            fight.challenge_proposals
            if in_placement and fight.challenge_proposals
            else list(fight.challenge_by_id.values())
        )
        return self.to_lua([self._challenge_table(challenge) for challenge in challenges])

    def get_selected_challenge(self) -> int:
        selected = self.game_state.fight.selected_challenge_ids
        return selected[-1] if selected else 0

    def is_challenge_validate(self, challenge_id: object) -> bool:
        challenge = self.game_state.fight.challenge_by_id.get(to_int(challenge_id) or 0)
        return challenge is not None and challenge.state != Challenge.CHALLENGE_FAILED

    def get_challenge_target(self, challenge_id: object) -> object:
        challenge = self.game_state.fight.challenge_by_id.get(to_int(challenge_id) or 0)
        if challenge is None or not challenge.targets:
            return None
        target = challenge.targets[0]
        return self.to_lua({"targetId": str(target.target_id), "targetCell": target.target_cell})

    def _challenge_table(self, challenge: Challenge) -> dict[str, object]:
        # The protocol numbers states differently from DoFarm, so expose the explicit name.
        return {
            "challengeId": challenge.challenge_id,
            "id": challenge.challenge_id,
            "state": Challenge.ChallengeState.Name(challenge.state),
            "xpBonus": challenge.xp_bonus,
            "dropBonus": challenge.drop_bonus,
        }

    def _fighters_by_id(self, enemies: bool) -> dict[str, dict[str, object]]:
        player_id = self.game_state.player.character_id
        player = self._actor(player_id)
        if player is None:
            return {}
        fighters: dict[str, dict[str, object]] = {}
        for actor in dict(self.game_state.entity.actor_by_id).values():
            if actor.actor_id == player_id or not actor.actor_information.HasField("fighter"):
                continue
            if actor.disposition.cell_id == -1 or (self._team(actor) != self._team(player)) != enemies:
                continue
            life = self.get_fighter_life(actor.actor_id)
            if life <= 0:
                continue
            fighters[str(actor.actor_id)] = {
                "id": str(actor.actor_id),
                "cellId": actor.disposition.cell_id,
                "life": life,
                "level": self.get_stat("level", actor.actor_id),
            }
        return fighters

    def _actor(self, fighter_id: object) -> ActorPositionInformation | None:
        actor_id = to_int(fighter_id)
        if actor_id is None:
            return None
        actor = self.game_state.entity.actor_by_id.get(actor_id)
        if actor is None or actor.disposition.cell_id == -1:
            return None
        return actor

    @staticmethod
    def _team(actor: ActorPositionInformation) -> int:
        return actor.actor_information.fighter.spawn_information.team

    def _own_spell_lvl(self, spell: object) -> SpellLevelsRootItem | None:
        own_spell = find_own_spell(self.game_state, spell)
        if own_spell is None:
            return None
        return DataReader().spell_lvl_by_spell_id[own_spell.spell_id][own_spell.spell_level - 1]

    def _spell_lvl_by_id(self, spell_id: int | None) -> SpellLevelsRootItem | None:
        if spell_id is None:
            return None
        own = next((spell for spell in self.game_state.fight.spells if spell.spell_id == spell_id), None)
        levels = DataReader().spell_lvl_by_spell_id.get(spell_id)
        if not levels:
            return None
        return levels[own.spell_level - 1] if own is not None else levels[0]
