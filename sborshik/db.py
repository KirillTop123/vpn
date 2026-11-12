"""SQLite: компании, склейка дублей, статусы, шаблоны, очередь сбора."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import threading
from pathlib import Path

import config
import segments
import textutil

LIST_FIELDS = ("phones", "emails", "rubrics", "tags", "reasons")
DICT_FIELDS = ("card_urls",)
TEXT_FIELDS = (
    "name", "address", "district", "city", "niche", "hours", "site", "telegram", "whatsapp", "max", "vk",
    "instagram", "booking", "site_status", "site_error", "site_found_by", "site_checked_at", "notes",
    "next_touch", "message",
)
NUM_FIELDS = (
    "rating", "reviews", "branches", "site_ssl", "site_calc", "site_form", "site_booking", "site_chat",
    "site_mobile", "site_year", "enriched",
)
COMPUTED = ("segment", "segment_reason", "not_my_client", "nmc_reason")
EXPORT_FIELDS = [
    ("id", "ID"), ("name", "Название"), ("rubrics", "Рубрики"), ("city", "Город"), ("district", "Район"),
    ("address", "Адрес"), ("rating", "Рейтинг"), ("reviews", "Отзывы"), ("phones", "Телефоны"),
    ("emails", "E-mail"), ("site", "Сайт"), ("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("max", "MAX"),
    ("vk", "VK"), ("instagram", "Instagram"), ("hours", "Часы работы"), ("booking", "Онлайн-запись"),
    ("card_urls", "Карточки"), ("site_status", "Сайт работает"), ("site_ssl", "SSL"),
    ("site_calc", "Калькулятор"), ("site_form", "Форма заявки"), ("site_booking", "Запись на сайте"),
    ("site_chat", "Чат на сайте"), ("site_mobile", "Мобильная версия"), ("site_year", "Год в футере"),
    ("segment", "Сегмент"), ("segment_reason", "Причина"), ("reasons", "Все наблюдения"),
    ("not_my_client", "Не мой клиент"), ("status", "Статус"), ("status_changed_at", "Статус изменён"),
    ("next_touch", "Следующее касание"), ("notes", "Заметки"), ("message", "Сообщение"), ("niche", "Ниша"),
    ("created_at", "Добавлена"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '', rubrics TEXT DEFAULT '[]', address TEXT DEFAULT '', district TEXT DEFAULT '',
    city TEXT DEFAULT '', niche TEXT DEFAULT '', rating REAL DEFAULT 0, reviews INTEGER DEFAULT 0,
    branches INTEGER DEFAULT 0, phones TEXT DEFAULT '[]', emails TEXT DEFAULT '[]', site TEXT DEFAULT '',
    telegram TEXT DEFAULT '', whatsapp TEXT DEFAULT '', max TEXT DEFAULT '', vk TEXT DEFAULT '',
    instagram TEXT DEFAULT '', hours TEXT DEFAULT '', booking TEXT DEFAULT '', card_urls TEXT DEFAULT '{}',
    site_status TEXT DEFAULT '', site_error TEXT DEFAULT '', site_found_by TEXT DEFAULT '',
    site_checked_at TEXT DEFAULT '', site_ssl INTEGER DEFAULT 0, site_calc INTEGER DEFAULT 0,
    site_form INTEGER DEFAULT 0, site_booking INTEGER DEFAULT 0, site_chat INTEGER DEFAULT 0,
    site_mobile INTEGER DEFAULT 0, site_year INTEGER DEFAULT 0,
    segment TEXT DEFAULT '', segment_reason TEXT DEFAULT '', reasons TEXT DEFAULT '[]', tags TEXT DEFAULT '[]',
    not_my_client INTEGER DEFAULT 0, nmc_reason TEXT DEFAULT '',
    status TEXT DEFAULT 'new', status_changed_at TEXT DEFAULT '', next_touch TEXT DEFAULT '',
    notes TEXT DEFAULT '', message TEXT DEFAULT '', enriched INTEGER DEFAULT 0, job_id INTEGER DEFAULT 0,
    created_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS company_keys (key TEXT PRIMARY KEY, company_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_keys_company ON company_keys(company_id);
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, params TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, finished_at TEXT DEFAULT '', found INTEGER DEFAULT 0, added INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, source TEXT NOT NULL, query TEXT NOT NULL,
    district TEXT DEFAULT '', status TEXT DEFAULT 'pending', page INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, task_id INTEGER NOT NULL, source TEXT NOT NULL,
    url TEXT NOT NULL, status TEXT DEFAULT 'pending', error TEXT DEFAULT '', UNIQUE(job_id, url)
);
"""

DEFAULT_TEMPLATES = [
    ("Первое сообщение", "Здравствуйте! Нашёл «{название}» на картах — у вас {отзывы} отзывов, видно, что клиенты довольны. "
     "Заметил одну вещь: {проблема}. Могу показать, как это исправить за пару дней. Удобно, если напишу подробнее?"),
    ("Повторное касание", "Здравствуйте! Писал вам на днях про «{название}». Если сейчас не до этого — скажите, "
     "вернусь позже. Если интересно, пришлю короткий пример."),
]

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path | None = None) -> None:
    """Открывает базу (или переоткрывает её в другой папке)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(str(path or config.db_path()), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        if not _conn.execute("SELECT 1 FROM templates LIMIT 1").fetchone():
            _conn.executemany("INSERT INTO templates(name, body) VALUES(?, ?)", DEFAULT_TEMPLATES)
        _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        connect()
    return _conn  # type: ignore[return-value]


def query(sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
    with _lock:
        return _db().execute(sql, args).fetchall()


def execute(sql: str, args: tuple | list = ()) -> int:
    with _lock:
        cur = _db().execute(sql, args)
        _db().commit()
        return cur.lastrowid or cur.rowcount


# ---------- настройки ----------

def get_settings() -> dict:
    result = json.loads(json.dumps(config.DEFAULT_SETTINGS))
    for row in query("SELECT key, value FROM settings"):
        try:
            result[row["key"]] = json.loads(row["value"])
        except ValueError:
            pass
    return result


def _check_setting(key: str, value):
    """Приводит значение настройки к нужному типу; мусор не сохраняется."""
    default = config.DEFAULT_SETTINGS[key]
    if key == "browser":
        if value not in ("auto", "chromium", "msedge", "chrome"):
            raise ValueError("Неизвестный браузер.")
        return value
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError("Стоп-слова должны быть списком.")
        return [str(v).strip()[:100] for v in value if str(v).strip()][:500]
    try:
        number = float(value) if isinstance(default, float) else int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"Настройка «{key}» должна быть числом.") from None
    if not 0 <= number <= 100000:
        raise ValueError(f"Настройка «{key}»: значение вне допустимого диапазона.")
    return number


def save_settings(values: dict) -> dict:
    values = {key: _check_setting(key, value) for key, value in values.items() if key in config.DEFAULT_SETTINGS}
    with _lock:
        for key, value in values.items():
            if key in config.DEFAULT_SETTINGS:
                _db().execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
                              (key, json.dumps(value, ensure_ascii=False)))
        _db().commit()
    recompute_segments()
    return get_settings()


# ---------- компании ----------

def _row_to_company(row: sqlite3.Row) -> dict:
    company = dict(row)
    for field in LIST_FIELDS:
        company[field] = json.loads(company.get(field) or "[]")
    for field in DICT_FIELDS:
        company[field] = json.loads(company.get(field) or "{}")
    return company


def _encode(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        out[key] = json.dumps(value, ensure_ascii=False) if key in LIST_FIELDS + DICT_FIELDS else value
    return out


def _keys_for(company: dict) -> list[str]:
    keys = [f"p:{p}" for p in company.get("phones") or []]
    if company.get("site") and textutil.is_company_site(company["site"]):
        keys.append("s:" + textutil.domain_of(company["site"]))
    name, address = textutil.norm_name(company.get("name", "")), textutil.norm_address(company.get("address", ""))
    if name and address:
        keys.append(f"n:{name}|{address}")
    return keys


def _clean(data: dict) -> dict:
    """Приводит сырые данные карточки к полям таблицы."""
    out: dict = {}
    for field in TEXT_FIELDS:
        if data.get(field):
            out[field] = str(data[field]).strip()
    for field in NUM_FIELDS:
        if data.get(field):
            try:
                out[field] = float(data[field]) if field == "rating" else int(float(data[field]))
            except (TypeError, ValueError):
                pass
    phones = []
    for raw in data.get("phones") or []:
        phone = textutil.norm_phone(raw)
        if phone and phone not in phones:
            phones.append(phone)
    out["phones"] = phones
    out["emails"] = list(dict.fromkeys(e.lower() for e in data.get("emails") or [] if e))
    out["rubrics"] = list(dict.fromkeys(r.strip() for r in data.get("rubrics") or [] if r and r.strip()))
    out["card_urls"] = dict(data.get("card_urls") or {})
    if out.get("site"):
        out["site"] = textutil.norm_site(out["site"]) if textutil.is_company_site(out["site"]) else ""
    return out


def _merge(old: dict, new: dict) -> dict:
    merged: dict = {}
    for field in ("phones", "emails", "rubrics"):
        merged[field] = list(dict.fromkeys((old.get(field) or []) + (new.get(field) or [])))
    merged["card_urls"] = {**(old.get("card_urls") or {}), **(new.get("card_urls") or {})}
    for field in TEXT_FIELDS + NUM_FIELDS:
        if field == "site_found_by" and old.get("site"):
            continue  # сайт уже был известен из карточки
        if field in new and new[field] and not old.get(field):
            merged[field] = new[field]
    if (new.get("reviews") or 0) > (old.get("reviews") or 0):
        merged["reviews"] = new["reviews"]
        if new.get("rating"):
            merged["rating"] = new["rating"]
    return merged


def _write(company_id: int, fields: dict) -> None:
    fields = dict(fields, updated_at=now())
    encoded = _encode(fields)
    sets = ", ".join(f"{k} = ?" for k in encoded)
    _db().execute(f"UPDATE companies SET {sets} WHERE id = ?", (*encoded.values(), company_id))


def _refresh(company_id: int, settings: dict | None = None) -> dict:
    """Пересчитывает сегмент и ключи дублей."""
    company = get_company(company_id)
    seg = segments.compute(company, settings or get_settings())
    _write(company_id, {k: seg[k] for k in ("segment", "segment_reason", "reasons", "tags", "not_my_client", "nmc_reason")})
    for key in _keys_for(company):
        _db().execute("INSERT OR IGNORE INTO company_keys(key, company_id) VALUES(?, ?)", (key, company_id))
    return get_company(company_id)


def find_duplicate(company: dict) -> int | None:
    keys = _keys_for(company)
    if not keys:
        return None
    marks = ",".join("?" * len(keys))
    rows = query(f"SELECT MIN(company_id) AS id FROM company_keys WHERE key IN ({marks})", keys)
    return rows[0]["id"] if rows and rows[0]["id"] else None


def upsert_company(data: dict, job_id: int = 0, settings: dict | None = None) -> tuple[int, bool]:
    """Добавляет компанию или склеивает с дублем. Возвращает (id, новая ли)."""
    new = _clean(data)
    if not new.get("name"):
        raise ValueError("у компании нет названия")
    with _lock:
        existing_id = find_duplicate(new)
        if existing_id:
            _write(existing_id, _merge(get_company(existing_id), new))
            created = False
            company_id = existing_id
        else:
            stamp = now()
            encoded = _encode(dict(new, job_id=job_id, created_at=stamp, updated_at=stamp, status="new",
                                   status_changed_at=stamp))
            cols = ", ".join(encoded)
            marks = ", ".join("?" * len(encoded))
            company_id = _db().execute(f"INSERT INTO companies({cols}) VALUES({marks})", tuple(encoded.values())).lastrowid
            _db().execute("INSERT INTO status_history(company_id, status, at) VALUES(?, 'new', ?)", (company_id, stamp))
            created = True
        _refresh(company_id, settings)
        _db().commit()
    return company_id, created


def update_company(company_id: int, fields: dict, settings: dict | None = None) -> dict:
    allowed = set(TEXT_FIELDS + NUM_FIELDS + LIST_FIELDS + DICT_FIELDS)
    fields = {k: v for k, v in fields.items() if k in allowed}
    with _lock:
        if fields:
            _write(company_id, fields)
        company = _refresh(company_id, settings)
        _db().commit()
    return company


def get_company(company_id: int) -> dict:
    rows = query("SELECT * FROM companies WHERE id = ?", (company_id,))
    if not rows:
        raise KeyError(f"компания {company_id} не найдена")
    return _row_to_company(rows[0])


def company_history(company_id: int) -> list[dict]:
    return [dict(r) for r in query("SELECT status, at FROM status_history WHERE company_id = ? ORDER BY id DESC", (company_id,))]


def set_status(company_id: int, status: str) -> dict:
    if status not in segments.STATUS_NAMES:
        raise ValueError(f"неизвестный статус: {status}")
    stamp = now()
    with _lock:
        _db().execute("UPDATE companies SET status = ?, status_changed_at = ?, updated_at = ? WHERE id = ?",
                      (status, stamp, stamp, company_id))
        _db().execute("INSERT INTO status_history(company_id, status, at) VALUES(?, ?, ?)", (company_id, status, stamp))
        _db().commit()
    return get_company(company_id)


def delete_companies(ids: list[int]) -> int:
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with _lock:
        for table, col in (("company_keys", "company_id"), ("status_history", "company_id"), ("companies", "id")):
            _db().execute(f"DELETE FROM {table} WHERE {col} IN ({marks})", ids)
        _db().commit()
    return len(ids)


SORTABLE = {"name", "city", "district", "rating", "reviews", "status", "segment", "created_at", "updated_at",
            "next_touch", "status_changed_at", "id"}


def _where(f: dict) -> tuple[str, list]:
    cond, args = [], []
    if f.get("q"):
        like = f"%{str(f['q']).lower()}%"
        cols = ("name", "address", "phones", "site", "rubrics", "notes", "emails", "district")
        cond.append("(" + " OR ".join(f"lower_ru({c}) LIKE ?" for c in cols) + ")")
        args += [like] * len(cols)
    for key in ("status", "city", "segment", "district"):
        if f.get(key):
            cond.append(f"{key} = ?")
            args.append(f[key])
    if f.get("tag"):
        cond.append("tags LIKE ?")
        args.append(f'%"{f["tag"]}"%')
    if f.get("job_id"):
        cond.append("job_id = ?")
        args.append(int(f["job_id"]))
    flags = {
        "has_tg": "telegram != ''", "has_wa": "whatsapp != ''",
        "only_phone": "phones != '[]' AND telegram = '' AND whatsapp = '' AND max = '' AND emails = '[]'",
        "no_site": "site = ''", "site_down": "site_status = 'down'", "no_booking": "booking = ''",
        "hide_nmc": "not_my_client = 0", "only_nmc": "not_my_client = 1",
    }
    for key, sql in flags.items():
        if f.get(key):
            cond.append(f"({sql})")
    if f.get("many_reviews"):
        cond.append("reviews >= ?")
        args.append(int(get_settings()["many_reviews"]))
    if f.get("ids"):
        ids = [int(i) for i in f["ids"]]
        cond.append(f"id IN ({','.join('?' * len(ids))})")
        args += ids
    return (" WHERE " + " AND ".join(cond)) if cond else "", args


def list_companies(filters: dict | None = None) -> dict:
    f = filters or {}
    where, args = _where(f)
    sort = f.get("sort") if f.get("sort") in SORTABLE else "id"
    direction = "ASC" if str(f.get("dir", "desc")).lower() == "asc" else "DESC"
    limit, offset = int(f.get("limit") or 100000), int(f.get("offset") or 0)
    with _lock:
        _db().create_function("lower_ru", 1, lambda s: (s or "").lower())
        total = _db().execute(f"SELECT COUNT(*) FROM companies{where}", args).fetchone()[0]
        rows = _db().execute(
            f"SELECT * FROM companies{where} ORDER BY {sort} {direction}, id DESC LIMIT ? OFFSET ?", (*args, limit, offset)
        ).fetchall()
    return {"total": total, "items": [_row_to_company(r) for r in rows]}


def facets() -> dict:
    cities = [r[0] for r in query("SELECT DISTINCT city FROM companies WHERE city != '' ORDER BY city")]
    segs = [dict(r) for r in query("SELECT segment AS name, COUNT(*) AS n FROM companies GROUP BY segment ORDER BY n DESC")]
    statuses = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) AS n FROM companies WHERE not_my_client = 0 GROUP BY status")}
    total = query("SELECT COUNT(*) AS n FROM companies")[0]["n"]
    return {"cities": cities, "segments": segs, "statuses": statuses, "total": total}


def recompute_segments() -> None:
    settings = get_settings()
    with _lock:
        for row in query("SELECT id FROM companies"):
            _refresh(row["id"], settings)
        _db().commit()


def today(settings: dict | None = None) -> dict:
    s = settings or get_settings()
    current = dt.datetime.now()

    def before(days: int) -> str:
        return (current - dt.timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")

    def pick(sql: str, args: tuple) -> list[dict]:
        return [_row_to_company(r) for r in query(f"SELECT * FROM companies WHERE not_my_client = 0 AND {sql} ORDER BY status_changed_at", args)]

    return {
        "planned": pick("next_touch != '' AND next_touch <= ? AND status NOT IN ('client', 'refused')", (current.strftime("%Y-%m-%d"),)),
        "read_silent": pick("status = 'read' AND status_changed_at <= ?", (before(s["read_silent_days"]),)),
        "no_reply": pick("status = 'written' AND status_changed_at <= ?", (before(s["no_reply_days"]),)),
    }


# ---------- шаблоны ----------

def list_templates() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM templates ORDER BY id")]


def save_template(template_id: int | None, name: str, body: str) -> int:
    if template_id:
        execute("UPDATE templates SET name = ?, body = ? WHERE id = ?", (name, body, template_id))
        return template_id
    return execute("INSERT INTO templates(name, body) VALUES(?, ?)", (name, body))


def delete_template(template_id: int) -> None:
    execute("DELETE FROM templates WHERE id = ?", (template_id,))


# ---------- резервная копия ----------

def backup() -> Path:
    target = config.backups_dir() / f"sborshik-{dt.datetime.now():%Y%m%d-%H%M%S}.db"
    with _lock:
        dest = sqlite3.connect(str(target))
        _db().backup(dest)
        dest.close()
    return target


def move_database(new_dir: str) -> Path:
    """Копирует базу в новую папку и переключается на неё."""
    global _conn
    with _lock:
        old_path = config.db_path()
        target_dir = Path(new_dir).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        new_path = target_dir / config.DB_FILE
        if new_path.resolve() != old_path.resolve():
            if not new_path.exists():
                _db().execute("PRAGMA wal_checkpoint(TRUNCATE)")
                shutil.copy2(old_path, new_path)
            config.set_data_dir(str(target_dir))
            connect(new_path)
    return new_path
