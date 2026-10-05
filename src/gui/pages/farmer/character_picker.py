from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox

from ankama_launcher_emulator.interfaces.local_storage import PreferredCharacter
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from src.controller.character_choice import (
    get_known_characters,
    get_preferred_character,
    set_preferred_character,
)

_AUTOMATIC_TEXT = "Automatic (last played)"


def _server_name(server_id: int) -> str:
    server = DataReader().server_by_id.get(server_id)
    return f"server {server_id}" if server is None else I18N().name_by_id.get(server.nameId, str(server_id))


class CharacterPicker(QWidget):
    """Chooses which character the socket mode logs in with; the list fills after a socket connection."""

    def __init__(self, login: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.login = login

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel("Character (socket):", self))
        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(320)
        layout.addWidget(self.combo)
        layout.addStretch()

        self._refreshing = False
        self.combo.currentIndexChanged.connect(self.on_character_changed)
        self.refresh()

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self.refresh()

    def refresh(self) -> None:
        self._refreshing = True
        try:
            self.combo.clear()
            self.combo.addItem(_AUTOMATIC_TEXT, userData=None)
            preferred = get_preferred_character(self.login)
            choices: list[tuple[PreferredCharacter, int | None]] = [
                (PreferredCharacter(server_id=character.server_id, name=character.name), character.level)
                for character in get_known_characters(self.login)
            ]
            if preferred is not None and preferred not in [choice for choice, _ in choices]:
                choices.append((preferred, None))
            for choice, level in sorted(choices, key=lambda item: (_server_name(item[0].server_id), item[0].name)):
                level_text = "" if level is None else f" (lvl {level})"
                self.combo.addItem(f"{choice.name} — {_server_name(choice.server_id)}{level_text}", userData=choice)
                if choice == preferred:
                    self.combo.setCurrentIndex(self.combo.count() - 1)
        finally:
            self._refreshing = False

    def on_character_changed(self) -> None:
        if self._refreshing:
            return
        choice = self.combo.currentData()
        set_preferred_character(self.login, choice if isinstance(choice, PreferredCharacter) else None)
