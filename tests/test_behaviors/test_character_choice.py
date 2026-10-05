from character_management_pb2 import CharacterListEvent, CharacterSelectionRequest
from google.protobuf.message import Message

from ankama_launcher_emulator.interfaces.local_storage import PreferredCharacter
from DBDofusUnity.datas.protos.non_obf.connection.login_message_pb2 import (
    CharacterInformation,
    Server,
    ServerInformation,
)
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import Character
from src.controller.character_choice import (
    NEW_ACCOUNT_SERVER_ID,
    CharacterTarget,
    choose_character_target,
    known_characters_from_servers,
)
from src.core.bot.bot import Bot

DAKAL = 353
SALAR = 352


def _server(server_id: int, *characters: tuple[str, str]) -> ServerInformation:
    return ServerInformation(
        server=Server(id=server_id),
        characters=[
            CharacterInformation(name=name, level=50, last_connection_date=date) for name, date in characters
        ],
    )


SERVERS = [
    _server(DAKAL, ("Panda", "2026-10-01T10:00:00+02:00"), ("Cra", "2026-10-04T10:00:00+02:00")),
    _server(SALAR, ("Iop", "2026-09-01T10:00:00+02:00")),
]


class TestChooseCharacterTarget:
    def test_preferred_character_selects_its_server(self) -> None:
        target, warning = choose_character_target(SERVERS, PreferredCharacter(server_id=SALAR, name="iop"))

        assert target == CharacterTarget(SALAR, "Iop")
        assert warning is None

    def test_without_preference_the_last_played_character_wins(self) -> None:
        target, warning = choose_character_target(SERVERS, None)

        assert target == CharacterTarget(DAKAL, "Cra")
        assert warning is None

    def test_missing_preferred_character_falls_back_to_last_played_with_a_warning(self) -> None:
        target, warning = choose_character_target(SERVERS, PreferredCharacter(server_id=SALAR, name="Gone"))

        assert target == CharacterTarget(DAKAL, "Cra")
        assert warning is not None

    def test_only_an_account_without_any_character_creates_one(self) -> None:
        target, _ = choose_character_target([_server(DAKAL), _server(SALAR)], None)

        assert target == CharacterTarget(NEW_ACCOUNT_SERVER_ID, None)

    def test_known_characters_list_every_server(self) -> None:
        known = known_characters_from_servers(SERVERS)

        assert [(character.server_id, character.name) for character in known] == [
            (DAKAL, "Panda"),
            (DAKAL, "Cra"),
            (SALAR, "Iop"),
        ]


def _game_character(character_id: int, name: str) -> Character:
    return Character(
        id=character_id,
        character_basic_information=Character.CharacterBasicInformation(name=name),
    )


class TestHandshakeCharacterSelection:
    def _selected_ids(self, runtime_bot: Bot, wanted_name: str | None) -> list[int]:
        sent_messages: list[Message] = []
        runtime_bot.event_manager.on_send_game_callback = sent_messages.append
        runtime_bot.game_state.player.character_name_to_select = wanted_name
        # The handshake arms an authentication timeout that would otherwise fire after the test.
        runtime_bot.event_manager.request_disconnect_callback = lambda: None

        runtime_bot.handshake_behavior.run(ticket="ticket")
        runtime_bot.event_manager.process_msg(
            CharacterListEvent(characters=[_game_character(1, "Panda"), _game_character(2, "Cra")])
        )

        return [message.character_id for message in sent_messages if isinstance(message, CharacterSelectionRequest)]

    def test_selects_the_chosen_character(self, runtime_bot: Bot) -> None:
        assert set(self._selected_ids(runtime_bot, "cra")) == {2}

    def test_unknown_name_selects_the_first_character(self, runtime_bot: Bot) -> None:
        assert set(self._selected_ids(runtime_bot, "Gone")) == {1}
