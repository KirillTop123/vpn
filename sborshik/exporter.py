"""Экспорт в Excel/CSV/JSON, «Экспорт для Claude» и импорт обратно."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import config
import db
import segments
import textutil

TITLES = dict(db.EXPORT_FIELDS)
BY_TITLE = {title.lower(): key for key, title in db.EXPORT_FIELDS}
YES_NO = ("site_ssl", "site_calc", "site_form", "site_booking", "site_chat", "site_mobile", "not_my_client")
IMPORTABLE = ("message", "notes", "next_touch", "status", "telegram", "whatsapp", "max", "vk", "instagram", "site",
              "phones", "emails")


def _flat(company: dict, field: str) -> str | int | float:
    value = company.get(field)
    if field == "phones":
        return "; ".join(textutil.pretty_phone(p) for p in value or [])
    if field == "card_urls":
        return "; ".join((value or {}).values())
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if field == "status":
        return segments.STATUS_NAMES.get(value, value)
    if field in YES_NO:
        return "да" if value else "нет"
    if field == "site_status":
        return {"ok": "да", "down": "нет", "unknown": "не удалось проверить"}.get(value, "")
    if field == "site_year":
        return value or ""
    return "" if value is None else value


def _target(prefix: str, ext: str) -> Path:
    return config.exports_dir() / f"{prefix}-{dt.datetime.now():%Y%m%d-%H%M%S}.{ext}"


def export(fmt: str, fields: list[str] | None, filters: dict | None) -> dict:
    fields = [f for f in (fields or [k for k, _ in db.EXPORT_FIELDS]) if f in TITLES]
    if "id" not in fields:
        fields.insert(0, "id")  # ID нужен, чтобы потом импортировать обратно
    items = db.list_companies(filters or {})["items"]
    if fmt == "xlsx":
        path = _target("baza", "xlsx")
        book = Workbook()
        sheet = book.active
        sheet.title = "Компании"
        sheet.append([TITLES[f] for f in fields])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="F5B942")
        for company in items:
            sheet.append([_flat(company, f) for f in fields])
        for index, field in enumerate(fields, 1):
            longest = max([len(TITLES[field])] + [len(str(_flat(c, field))) for c in items[:200]])
            sheet.column_dimensions[get_column_letter(index)].width = min(60, max(8, longest + 2))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        book.save(path)
    elif fmt == "csv":
        path = _target("baza", "csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([TITLES[f] for f in fields])
            for company in items:
                writer.writerow([_flat(company, f) for f in fields])
    elif fmt == "json":
        path = _target("baza", "json")
        path.write_text(json.dumps([{f: c.get(f) for f in fields} for c in items], ensure_ascii=False, indent=2), "utf-8")
    else:
        raise ValueError("Неизвестный формат. Доступны: xlsx, csv, json.")
    return {"path": str(path), "count": len(items)}


def export_for_claude(filters: dict | None) -> dict:
    items = db.list_companies(filters or {})["items"]
    skip = ("tags", "enriched", "job_id", "updated_at")
    settings = db.get_settings()
    bases = {b["id"]: b for b in db.list_bases()}
    payload = {
        "инструкция": (
            "Это база компаний малого бизнеса. Для каждой компании напиши короткое первое сообщение "
            "(2–4 предложения, без воды), опираясь на поля segment, segment_reason, reasons (все найденные проблемы) "
            "и заготовка_сообщения. Не хвали отзывы, если их мало. "
            "Верни JSON-массив объектов вида {\"id\": ..., \"message\": \"...\"} — файл в таком виде "
            "можно импортировать обратно в «Сборщик баз», сообщения привяжутся по id."
        ),
        "компании": [
            {**{k: v for k, v in c.items() if k not in skip}, "status_title": segments.STATUS_NAMES.get(c["status"], c["status"]),
             "заготовка_сообщения": segments.pitch(c, settings, bases.get(c.get("base_id")))}
            for c in items
        ],
    }
    path = _target("dlya-claude", "json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return {"path": str(path), "count": len(items)}


def _rows_from_file(filename: str, content: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith(".json"):
        data = json.loads(content.decode("utf-8-sig"))
        if isinstance(data, dict):
            data = data.get("компании") or data.get("companies") or data.get("items") or []
        return [row for row in data if isinstance(row, dict)]
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", "replace")
        delimiter = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    if name.endswith(".xlsx"):
        sheet = load_workbook(io.BytesIO(content), read_only=True).active
        rows = list(sheet.iter_rows(values_only=True))
        return [dict(zip([str(h or "") for h in rows[0]], row)) for row in rows[1:]] if rows else []
    raise ValueError("Поддерживаются файлы .json, .csv и .xlsx.")


def import_file(filename: str, content: bytes) -> dict:
    """Объединяет строки файла с базой по ID. Меняет только сообщение, заметки,
    статус, дату касания и контакты."""
    status_by_title = {title.lower(): key for key, title in segments.STATUSES}
    updated, skipped = 0, 0
    for raw in _rows_from_file(filename, content):
        row = {BY_TITLE.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in raw.items()}
        try:
            company_id = int(float(row.get("id") or 0))
            db.get_company(company_id)
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
        fields = {}
        for key in IMPORTABLE:
            value = row.get(key)
            if value in (None, ""):
                continue
            if key in ("phones", "emails"):
                parts = value if isinstance(value, list) else str(value).replace(",", ";").split(";")
                parts = [p.strip() for p in parts if str(p).strip()]
                value = [textutil.norm_phone(p) for p in parts if textutil.norm_phone(p)] if key == "phones" else parts
                if not value:
                    continue
            if key == "status":
                status = status_by_title.get(str(value).strip().lower(), str(value).strip())
                if status in segments.STATUS_NAMES and status != db.get_company(company_id)["status"]:
                    db.set_status(company_id, status)
                continue
            fields[key] = value
        db.update_company(company_id, fields)
        updated += 1
    return {"updated": updated, "skipped": skipped}
