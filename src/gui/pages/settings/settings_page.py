from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, SegmentedWidget, SimpleCardWidget, TitleLabel

from src.gui import theme

from src.gui.pages.settings.assignment_panel import AssignmentSettingsPanel
from src.gui.pages.settings.behavior_panel import BehaviorSettingsPanel
from src.gui.pages.settings.mail_panel import MailSettingsPanel
from src.gui.pages.settings.payment_panel import PaymentSettingsPanel
from src.gui.pages.settings.proxy_panel import ProxySettingsPanel
from src.gui.pages.settings.schedule_panel import ScheduleSettingsPanel
from src.gui.pages.settings.services_panel import ServicesSettingsPanel


class SettingsPage(QWidget):
    schedules_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel("Settings", self))
        description = BodyLabel("Configure behaviors, accounts, schedules and services.", self)
        theme.set_label_color(description, theme.TEXT_MUTED)
        layout.addWidget(description)
        self.navigation = SegmentedWidget(self)
        layout.addWidget(self.navigation)
        card = SimpleCardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        self.stack = QStackedWidget(card)
        card_layout.addWidget(self.stack)
        layout.addWidget(card, 1)
        self.behaviors = BehaviorSettingsPanel()
        self.mail = MailSettingsPanel()
        self.proxies = ProxySettingsPanel()
        self.schedules = ScheduleSettingsPanel()
        self.assignments = AssignmentSettingsPanel()
        self.services = ServicesSettingsPanel()
        self.payments = PaymentSettingsPanel()
        self.schedules.changed.connect(self.schedules_changed.emit)
        self.assignments.changed.connect(self.schedules_changed.emit)
        for index, (label, panel) in enumerate(
            [
                ("Behaviors", self.behaviors),
                ("Email", self.mail),
                ("Proxies", self.proxies),
                ("Schedules", self.schedules),
                ("Accounts", self.assignments),
                ("Services", self.services),
                ("Payments", self.payments),
            ]
        ):
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            panel.setAutoFillBackground(False)
            self.stack.addWidget(scroll)
            self.navigation.addItem(
                str(index),
                label,
                onClick=lambda _checked=False, index=index: self.stack.setCurrentIndex(index),
            )
            self.navigation.widget(str(index)).setFixedHeight(44)
        self.navigation.setCurrentItem("0")
