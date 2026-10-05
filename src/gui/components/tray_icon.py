from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


class TrayIcon(QSystemTrayIcon):
    """Notification-area icon that takes over from the taskbar entry while the window is minimized."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window.windowIcon(), window)
        self.window = window
        self.setToolTip(window.windowTitle())

        menu = QMenu(window)
        show_action = QAction("Show Bill", menu)
        show_action.triggered.connect(self.restore_window)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)

        self.activated.connect(self.on_activated)

    def on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_window()

    def restore_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self) -> None:
        # Show the window so the shutdown progress stays visible, then use the normal close path.
        self.restore_window()
        self.window.close()
