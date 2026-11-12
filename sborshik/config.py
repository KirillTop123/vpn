"""Пути, настройки по умолчанию и загрузка редактируемых конфигов."""
from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Сборщик баз"
APP_DIR_NAME = "SborshikBaz"
DB_FILE = "sborshik.db"


def resource_dir() -> Path:
    """Папка с файлами программы (в .exe — временная папка PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Папка пользователя: указатель на базу, логи, правки конфигов."""
    override = os.environ.get("SBORSHIK_HOME")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_DIR_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _pointer_file() -> Path:
    return user_dir() / "config.json"


def data_dir() -> Path:
    """Папка, где лежит файл базы (меняется в настройках)."""
    try:
        saved = json.loads(_pointer_file().read_text("utf-8")).get("data_dir")
        if saved:
            path = Path(saved)
            path.mkdir(parents=True, exist_ok=True)
            return path
    except (OSError, ValueError):
        pass
    return user_dir()


def set_data_dir(path: str) -> Path:
    target = Path(path).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    _pointer_file().write_text(json.dumps({"data_dir": str(target)}, ensure_ascii=False), "utf-8")
    return target


def db_path() -> Path:
    return data_dir() / DB_FILE


def exports_dir() -> Path:
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json_config(name: str) -> dict:
    """Читает конфиг из data/. Если в папке пользователя лежит файл с тем же
    именем, берётся он: так селекторы можно чинить без пересборки .exe."""
    custom = user_dir() / name
    source = custom if custom.exists() else resource_dir() / "data" / name
    return json.loads(source.read_text("utf-8"))


def config_location(name: str) -> dict:
    custom = user_dir() / name
    return {"builtin": str(resource_dir() / "data" / name), "custom": str(custom), "custom_exists": custom.exists()}


DEFAULT_SETTINGS = {
    # вежливый режим
    "delay_min": 2.0,
    "delay_max": 5.0,
    "cards_per_hour": 600,   # на каждый источник
    "windows_per_source": 2,  # окон браузера на один источник (1–3)
    "site_threads": 6,        # сколько сайтов компаний проверять одновременно
    "max_pages": 20,
    "page_timeout": 45,
    "browser": "auto",  # auto | chromium | msedge | chrome
    # пороги
    "many_reviews": 50,
    "few_reviews": 5,
    "low_rating": 4.0,
    "read_silent_days": 2,
    "no_reply_days": 7,
    "network_branches": 5,
    # кто пишет (подставляется в шаблоны)
    "my_name": "",
    # «не мой клиент»
    "stop_words": [
        "дилер", "официальный дилер", "дилерский центр", "франшиза", "федеральная сеть",
        "гипермаркет", "леруа", "лемана про", "всеинструменты", "петрович", "озон", "wildberries",
        "яндекс", "сбер", "мтс", "билайн", "мегафон", "дом.рф", "газпром", "лукойл", "роснефть",
        "fit service", "вилгуд", "fix price", "магнит", "пятёрочка",
    ],
}

_logger_ready = False


def setup_logging() -> logging.Logger:
    global _logger_ready
    logger = logging.getLogger("sborshik")
    if not _logger_ready:
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(user_dir() / "sborshik.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        _logger_ready = True
    return logger
