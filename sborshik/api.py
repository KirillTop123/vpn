"""Локальный сервер приложения: API для интерфейса и раздача ui/."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import db
import exporter
import segments
import variants
from collector import SOURCE_TITLES, collector, mark_interrupted_jobs, rechecker

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None)
UI_DIR = config.resource_dir() / "ui"
FLAGS = ("has_tg", "has_wa", "only_phone", "no_site", "site_down", "no_booking", "many_reviews", "hide_nmc", "only_nmc")
log = config.setup_logging()


# Токен создаётся при каждом запуске и вшивается в страницу интерфейса. Без него API не отвечает,
# поэтому посторонний сайт, открытый в браузере, не может слать запросы приложению.
APP_TOKEN = secrets.token_urlsafe(32)
LOCAL_HOSTS = ("127.0.0.1", "localhost")


@app.middleware("http")
async def _local_only(request: Request, call_next):
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in LOCAL_HOSTS:  # защита от подмены DNS
        return JSONResponse({"error": "Доступ только с этого компьютера."}, status_code=403)
    if request.url.path.startswith("/api/"):
        if not secrets.compare_digest(request.headers.get("x-app-token", ""), APP_TOKEN):
            return JSONResponse({"error": "Запрос отклонён: откройте приложение заново."}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
def _startup() -> None:
    db.connect()
    mark_interrupted_jobs()
    db.recompute_segments()  # правила поиска проблем могли обновиться вместе с программой


@app.exception_handler(Exception)
async def _errors(_request: Request, exc: Exception):
    if isinstance(exc, (ValueError, RuntimeError, KeyError)):
        return JSONResponse({"error": str(exc).strip("'\"")}, status_code=400)
    log.exception("ошибка сервера")
    return JSONResponse({"error": f"Внутренняя ошибка: {exc}. Подробности в файле журнала."}, status_code=500)


def _filters(source: dict) -> dict:
    out = {}
    for key, value in source.items():
        if value in ("", None):
            continue
        if key in FLAGS:
            if str(value).lower() in ("1", "true", "yes", "on"):
                out[key] = 1
        else:
            out[key] = value
    return out


@app.get("/api/meta")
def meta():
    return {
        "app": config.APP_NAME,
        "statuses": [{"key": k, "title": t} for k, t in segments.STATUSES],
        "sources": [{"key": k, "title": t} for k, t in SOURCE_TITLES.items()],
        "export_fields": [{"key": k, "title": t} for k, t in db.EXPORT_FIELDS],
        "cities": variants.known_cities(),
        "paths": {"db": str(config.db_path()), "data_dir": str(config.data_dir()), "exports": str(config.exports_dir()),
                  "log": str(config.user_dir() / "sborshik.log"), "selectors": config.config_location("selectors.json")},
    }


@app.post("/api/variants")
async def make_variants(request: Request):
    body = await request.json()
    return {"queries": variants.expand_niche(body.get("niche", "")), "districts": variants.districts(body.get("city", ""))}


# ---------- сбор ----------

@app.get("/api/job/status")
def job_status(since: int = 0):
    return collector.snapshot(since)


@app.post("/api/job/start")
async def job_start(request: Request):
    return {"job_id": collector.start(await request.json())}


@app.post("/api/job/{action}")
async def job_action(action: str, request: Request):
    if action == "pause":
        collector.pause()
    elif action == "resume":
        collector.resume()
    elif action == "stop":
        collector.stop()
    elif action == "resume_job":
        collector.resume_job(int((await request.json()).get("job_id", 0)))
    else:
        raise HTTPException(404)
    return collector.snapshot()


# ---------- база ----------

@app.get("/api/companies")
def companies(request: Request):
    return db.list_companies(_filters(dict(request.query_params)))


@app.get("/api/companies/{company_id}")
def company(company_id: int):
    data = db.get_company(company_id)
    base = db.get_base(data.get("base_id") or 0)
    return {**data, "history": db.company_history(company_id), "base_name": base.get("name", ""),
            "pitch": segments.pitch(data, db.get_settings(), base)}


@app.get("/api/bases")
def bases():
    return db.list_bases()


@app.patch("/api/bases/{base_id}")
async def base_update(base_id: int, request: Request):
    body = await request.json()
    db.update_base(base_id, body.get("name"), body.get("intro"))
    return db.get_base(base_id)


@app.delete("/api/bases/{base_id}")
def base_delete(base_id: int):
    if collector.busy():
        raise RuntimeError("Сначала остановите сбор.")
    return {"deleted": db.delete_base(base_id)}


@app.patch("/api/companies/{company_id}")
async def company_update(company_id: int, request: Request):
    body = await request.json()
    allowed = ("notes", "next_touch", "message", "telegram", "whatsapp", "max", "vk", "instagram", "site", "phones", "emails", "name")
    db.update_company(company_id, {k: v for k, v in body.items() if k in allowed})
    return company(company_id)


@app.post("/api/companies/{company_id}/status")
async def company_status(company_id: int, request: Request):
    db.set_status(company_id, (await request.json()).get("status", ""))
    return company(company_id)


@app.post("/api/companies/delete")
async def companies_delete(request: Request):
    return {"deleted": db.delete_companies([int(i) for i in (await request.json()).get("ids", [])])}


@app.post("/api/recheck")
async def recheck(request: Request):
    return {"count": rechecker.start(int((await request.json()).get("base_id") or 0))}


@app.get("/api/facets")
def facets(base_id: int = 0):
    return db.facets(base_id)


@app.get("/api/today")
def today():
    return db.today()


# ---------- шаблоны ----------

@app.get("/api/templates")
def templates():
    return db.list_templates()


@app.post("/api/templates")
async def template_save(request: Request):
    body = await request.json()
    if not (body.get("name") or "").strip() or not (body.get("body") or "").strip():
        raise ValueError("У шаблона должны быть название и текст.")
    return {"id": db.save_template(body.get("id"), body["name"].strip(), body["body"].strip())}


@app.delete("/api/templates/{template_id}")
def template_delete(template_id: int):
    db.delete_template(template_id)
    return {"ok": True}


# ---------- настройки ----------

@app.get("/api/settings")
def settings():
    return db.get_settings()


@app.post("/api/settings")
async def settings_save(request: Request):
    body = await request.json()
    if "delay_min" in body and "delay_max" in body and float(body["delay_min"]) > float(body["delay_max"]):
        raise ValueError("Минимальная пауза не может быть больше максимальной.")
    if "delay_min" in body and float(body["delay_min"]) < 1:
        raise ValueError("Пауза между карточками не может быть меньше 1 секунды: источники начнут блокировать.")
    return db.save_settings(body)


@app.post("/api/settings/data_dir")
async def settings_data_dir(request: Request):
    if collector.busy():
        raise RuntimeError("Сначала остановите сбор.")
    path = ((await request.json()).get("path") or "").strip()
    if not path:
        raise ValueError("Укажите папку.")
    try:
        return {"db": str(db.move_database(path))}
    except OSError as exc:
        raise ValueError(f"Не получилось перенести базу в эту папку: {exc}") from exc


@app.post("/api/backup")
def backup():
    return {"path": str(db.backup())}


# ---------- экспорт / импорт ----------

@app.post("/api/export")
async def export(request: Request):
    body = await request.json()
    filters = _filters(body.get("filters") or {})
    if body.get("claude"):
        return exporter.export_for_claude(filters)
    return exporter.export(body.get("format", "xlsx"), body.get("fields"), filters)


@app.post("/api/import")
async def import_(request: Request, filename: str):
    try:
        return exporter.import_file(filename, await request.body())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Не удалось прочитать файл: {exc}") from exc


# ---------- открыть ссылку / папку во внешней программе ----------

def _open_external(target: str) -> None:
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif target.startswith(("http", "tel:", "mailto:", "tg:")):
        webbrowser.open(target)
    else:
        subprocess.Popen(["xdg-open", target])


@app.post("/api/open")
async def open_link(request: Request):
    body = await request.json()
    url, path = body.get("url", ""), body.get("path", "")
    if url:
        if not url.lower().startswith(("http://", "https://", "tel:", "mailto:", "tg://")):
            raise ValueError("Такую ссылку открыть нельзя.")
        _open_external(url)
    elif path:
        target = Path(path)
        allowed = [config.data_dir().resolve(), config.user_dir().resolve()]
        if not any(str(target.resolve()).startswith(str(root)) for root in allowed):
            raise ValueError("Можно открывать только папки программы.")
        _open_external(str(target if target.is_dir() else target.parent))
    return {"ok": True}


@app.get("/")
def index():
    page = (UI_DIR / "index.html").read_text("utf-8").replace("__APP_TOKEN__", APP_TOKEN)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
