from pathlib import Path

from ankama_launcher_emulator.controller.bot_storage import BotStorageController
from ankama_launcher_emulator.interfaces.local_storage import BotRecord


def get_fight_script_path(login: str) -> Path | None:
    record = BotStorageController().get_record(login)
    if record is None or record.fight_script_path is None:
        return None
    return Path(record.fight_script_path)


def set_fight_script_path(login: str, path: Path | None) -> None:
    def assign(record: BotRecord) -> None:
        record.fight_script_path = None if path is None else str(path)

    BotStorageController().update_record(login, assign)


def fight_script_selects_challenges(login: str) -> bool:
    path = get_fight_script_path(login)
    return path is not None and path.is_file()
