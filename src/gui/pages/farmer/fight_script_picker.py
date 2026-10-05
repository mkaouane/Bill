from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, PushButton

from src.core.engine.lua_fight.storage import get_fight_script_path, set_fight_script_path
from src.gui import theme

_NO_SCRIPT_TEXT = "None (built-in AI)"


class FightScriptPicker(QWidget):
    """Chooses the DoFarm-compatible Lua script that drives this account's fights."""

    def __init__(self, login: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.login = login

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        layout.addWidget(BodyLabel("Fight script:", self))
        self.path_label = CaptionLabel(self)
        theme.set_label_color(self.path_label, theme.TEXT_MUTED)
        layout.addWidget(self.path_label, 1)

        self.choose_button = PushButton("Choose…", self)
        self.choose_button.clicked.connect(self.on_choose_clicked)
        layout.addWidget(self.choose_button)

        self.remove_button = PushButton("Remove", self)
        self.remove_button.clicked.connect(self.on_remove_clicked)
        layout.addWidget(self.remove_button)

        self.refresh()

    def refresh(self) -> None:
        path = get_fight_script_path(self.login)
        if path is None:
            self.path_label.setText(_NO_SCRIPT_TEXT)
            self.path_label.setToolTip("")
        elif path.is_file():
            self.path_label.setText(path.name)
            self.path_label.setToolTip(str(path))
        else:
            self.path_label.setText(f"{path.name} (file not found, built-in AI is used)")
            self.path_label.setToolTip(str(path))
        self.remove_button.setEnabled(path is not None)

    def on_choose_clicked(self) -> None:
        current = get_fight_script_path(self.login)
        start_dir = str(current.parent) if current is not None else str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(self, "Fight script", start_dir, "Lua scripts (*.lua)")
        if not selected:
            return
        set_fight_script_path(self.login, Path(selected))
        self.refresh()

    def on_remove_clicked(self) -> None:
        set_fight_script_path(self.login, None)
        self.refresh()
