from collections.abc import Iterable
from datetime import UTC, datetime
from typing import NamedTuple

from ankama_launcher_emulator.controller.bot_storage import BotStorageController
from ankama_launcher_emulator.interfaces.local_storage import (
    BotRecord,
    KnownCharacter,
    PreferredCharacter,
)
from DBDofusUnity.datas.protos.non_obf.connection.login_message_pb2 import (
    CharacterInformation,
    ServerInformation,
)
from DBDofusUnity.dofus_unity_reader.game_constants.server import ServerEnum

# Brand-new accounts get their first character on the server the bot was built for.
NEW_ACCOUNT_SERVER_ID = ServerEnum.BRIAL.value


class CharacterTarget(NamedTuple):
    server_id: int
    # None means the account has no character anywhere and one must be created.
    character_name: str | None


def known_characters_from_servers(servers: Iterable[ServerInformation]) -> list[KnownCharacter]:
    return [
        KnownCharacter(
            server_id=server.server.id,
            name=character.name,
            level=character.level,
            breed=CharacterInformation.Breed.Name(character.breed),
        )
        for server in servers
        for character in server.characters
    ]


_NEVER_CONNECTED = datetime(1970, 1, 1, tzinfo=UTC)


def _last_connection(character: CharacterInformation) -> datetime:
    try:
        connected_at = datetime.fromisoformat(character.last_connection_date)
    except ValueError:
        return _NEVER_CONNECTED
    return connected_at if connected_at.tzinfo is not None else connected_at.replace(tzinfo=UTC)


def choose_character_target(
    servers: Iterable[ServerInformation],
    preferred: PreferredCharacter | None,
) -> tuple[CharacterTarget, str | None]:
    """Pick the server and character to play; also returns a warning when the preferred one is gone."""
    candidates = [(server.server.id, character) for server in servers for character in server.characters]
    warning = None
    if preferred is not None:
        for server_id, character in candidates:
            if server_id == preferred.server_id and character.name.casefold() == preferred.name.casefold():
                return CharacterTarget(server_id, character.name), None
        warning = f"Chosen character {preferred.name} not found on server {preferred.server_id}, using last played"
    if not candidates:
        return CharacterTarget(NEW_ACCOUNT_SERVER_ID, None), warning
    server_id, character = max(candidates, key=lambda candidate: _last_connection(candidate[1]))
    return CharacterTarget(server_id, character.name), warning


def record_known_characters(login: str, characters: list[KnownCharacter]) -> None:
    """Remember the account's characters for the picker; never blocks a login for an unregistered account."""
    storage = BotStorageController()
    if storage.get_record(login) is None:
        return

    def assign(record: BotRecord) -> None:
        record.known_characters = characters

    storage.update_record(login, assign)


def get_known_characters(login: str) -> list[KnownCharacter]:
    record = BotStorageController().get_record(login)
    return [] if record is None else list(record.known_characters)


def get_preferred_character(login: str) -> PreferredCharacter | None:
    record = BotStorageController().get_record(login)
    return None if record is None else record.preferred_character


def set_preferred_character(login: str, preferred: PreferredCharacter | None) -> None:
    def assign(record: BotRecord) -> None:
        record.preferred_character = preferred

    BotStorageController().update_record(login, assign)
