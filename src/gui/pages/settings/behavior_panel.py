from qfluentwidgets import BodyLabel, SpinBox
from qfluentwidgets.components.widgets.check_box import CheckBox

from src.controller.settings import SettingsService
from src.core.config import MAX_MONSTER_GROUP_SIZE, BehaviorSettings, GlobalSettings
from src.gui.pages.settings.settings_panel import SettingsPanel

BEHAVIOR_LABELS = {
    "do_fighter": "Automatic combat",
    "do_sale_hotel": "Marketplace sales",
    "do_craft": "Automatic crafting",
    "do_use_guild_chest": "Use guild chest",
    "do_dungeon": "Donjons",
    "do_idle": "Breaks during sessions",
    "enable_auto_equipment_market_purchases": "Allow equipment purchases",
    "enable_auto_ogrine_subscriptions": "Allow Ogrine subscriptions",
    "enable_auto_paysafecard_subscriptions": "Allow Paysafecard subscriptions",
}


class BehaviorSettingsPanel(SettingsPanel):
    def __init__(self) -> None:
        super().__init__(
            "Behaviors apply the next time the bot starts manually or on schedule. "
            "Account automation applies to the next operation; the current one finishes normally."
        )
        self.checks: dict[str, CheckBox] = {}
        for name, label in BEHAVIOR_LABELS.items():
            check = CheckBox(label, self)
            self.form.addRow(check)
            self.checks[name] = check
        self.group_min_size = self._group_size_spin_box("Monster group size: minimum")
        self.group_max_size = self._group_size_spin_box("Monster group size: maximum")
        # Keep the range valid while editing instead of rejecting it on save.
        self.group_min_size.valueChanged.connect(self.group_max_size.setMinimum)
        self.group_max_size.valueChanged.connect(self.group_min_size.setMaximum)
        self.automation = CheckBox("Automatically create and authenticate accounts", self)
        self.form.addRow(self.automation)

    def _group_size_spin_box(self, label: str) -> SpinBox:
        spin_box = SpinBox(self)
        spin_box.setRange(1, MAX_MONSTER_GROUP_SIZE)
        self.form.addRow(BodyLabel(label, self), spin_box)
        return spin_box

    def reload(self) -> None:
        def render(settings: GlobalSettings) -> None:
            for name, check in self.checks.items():
                check.setChecked(getattr(settings.behaviors, name))
            self.group_min_size.setRange(1, MAX_MONSTER_GROUP_SIZE)
            self.group_max_size.setRange(1, MAX_MONSTER_GROUP_SIZE)
            self.group_min_size.setValue(settings.behaviors.fight_group_min_size)
            self.group_max_size.setValue(settings.behaviors.fight_group_max_size)
            self.automation.setChecked(settings.enable_account_automation)

        self.perform(SettingsService().get, render)

    def save(self) -> None:
        behaviors = BehaviorSettings.model_validate(
            {
                **{name: check.isChecked() for name, check in self.checks.items()},
                "fight_group_min_size": self.group_min_size.value(),
                "fight_group_max_size": self.group_max_size.value(),
            }
        )
        automation = self.automation.isChecked()

        self.perform(
            lambda: SettingsService().update_behaviors(behaviors, automation),
            lambda _: self.reload(),
        )
