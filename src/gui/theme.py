from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentLabelBase, Theme, setCustomStyleSheet, setTheme, setThemeColor
from qfluentwidgets.window.fluent_window import FluentWindowBase

BACKGROUND = QColor("#15120E")
SURFACE = QColor("#1F1A14")
SURFACE_RAISED = QColor("#2A231B")
BORDER = QColor("#3A3026")
ACCENT = QColor("#8BC34A")
GOLD = QColor("#D4A93C")
TEXT = QColor("#EDE6D8")
TEXT_MUTED = QColor("#A89F8D")
SUCCESS = QColor("#7CC24A")
ERROR = QColor("#E0574F")


def apply_application_theme() -> None:
    setTheme(Theme.DARK)
    setThemeColor(ACCENT)


def apply_window_theme(window: FluentWindowBase, stacked_widget: QWidget) -> None:
    # Mica lets the desktop wallpaper bleed through, which would override the palette background.
    window.setMicaEffectEnabled(False)
    window.setCustomBackgroundColor(BACKGROUND, BACKGROUND)
    stacked_qss = f"""
        StackedWidget {{
            background-color: {SURFACE.name()};
            border: 1px solid {BORDER.name()};
            border-right: none;
            border-bottom: none;
            border-top-left-radius: 12px;
        }}
    """
    setCustomStyleSheet(stacked_widget, stacked_qss, stacked_qss)


def set_label_color(label: FluentLabelBase, color: QColor) -> None:
    label.setTextColor(color, color)
