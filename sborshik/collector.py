"""Движок сбора: очередь задач, вежливый режим, пауза/стоп, капча, возобновление."""
from __future__ import annotations

import collections
import json
import random
import threading
import time

import config
import db
import variants
from browser import Browser, BrowserError
from enrich import site_check
from sources import base, twogis, yandex_maps, yandex_search

SOURCES = {"twogis": twogis, "yandex_maps": yandex_maps, "yandex_search": yandex_search}
SOURCE_TITLES = {"twogis": "2ГИС", "yandex_maps": "Яндекс Карты", "yandex_search": "Поиск Яндекса"}
CARD_KEYS = {"twogis": "2gis", "yandex_maps": "yandex_maps", "yandex_search": "yandex_search"}
CAPTCHA_MESSAGE = "Решите капчу в окне браузера и нажмите «Продолжить»"
BLOCK_MESSAGE = "Сайт ограничил доступ. Подождите, проверьте страницу в окне браузера и нажмите «Продолжить»"


class Collector:
    def __init__(self):
        self.log_file = config.setup_logging()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume = threading.Event()
        self._logs: collections.deque = collections.deque(maxlen=500)
        self._log_id = 0
        self.status = "idle"  # idle | running | paused | captcha | stopping
        self.message = ""
        self.job_id = 0
        self.current = ""
        self.settings: dict = {}
        self.page = None
        self._opened: collections.deque = collections.deque()  # время открытия страниц за последний час

    # ---------- управление ----------

    def start(self, params: dict) -> int:
        if self.busy():
            raise RuntimeError("Сбор уже идёт. Остановите его или дождитесь окончания.")
        queries = [q.strip() for q in params.get("queries") or [] if q.strip()]
        sources = [s for s in params.get("sources") or [] if s in SOURCES]
        city = (params.get("city") or "").strip()
        if not city or not queries or not sources:
            raise ValueError("Укажите город, хотя бы один запрос и хотя бы один источник.")
        districts = [d.strip() for d in params.get("districts") or [] if d.strip()] or [""]
        clean = {"city": city, "niche": (params.get("niche") or queries[0]).strip(), "queries": queries,
                 "districts": [d for d in districts if d], "sources": sources,
                 "enrich": bool(params.get("enrich", True)), "find_sites": bool(params.get("find_sites", True))}
        job_id = db.execute("INSERT INTO jobs(params, status, created_at) VALUES(?, 'running', ?)",
                            (json.dumps(clean, ensure_ascii=False), db.now()))
        for source in sources:
            for query in queries:
                for district in districts:
                    db.execute("INSERT INTO job_tasks(job_id, source, query, district) VALUES(?, ?, ?, ?)",
                               (job_id, source, query, district))
        self._launch(job_id)
        return job_id

    def resume_job(self, job_id: int) -> None:
        if self.busy():
            raise RuntimeError("Сбор уже идёт.")
        if not db.query("SELECT 1 FROM jobs WHERE id = ?", (job_id,)):
            raise ValueError("Такой сбор не найден.")
        db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
        self._launch(job_id)

    def _launch(self, job_id: int) -> None:
        self._stop.clear()
        self._pause.clear()
        self._resume.clear()
        self.job_id, self.status, self.message, self.current = job_id, "running", "", ""
        self._thread = threading.Thread(target=self._run, args=(job_id,), daemon=True, name="collector")
        self._thread.start()

    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def pause(self) -> None:
        if self.busy() and self.status == "running":
            self._pause.set()
            self.status = "paused"
            self.log("Пауза. Нажмите «Продолжить», чтобы идти дальше.")

    def resume(self) -> None:
        self._pause.clear()
        self._resume.set()

    def stop(self) -> None:
        if self.busy():
            self.status = "stopping"
            self._stop.set()
            self._resume.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ---------- состояние для интерфейса ----------

    def log(self, text: str, level: str = "info") -> None:
        with self._lock:
            self._log_id += 1
            self._logs.append({"id": self._log_id, "time": time.strftime("%H:%M:%S"), "level": level, "text": text})
        getattr(self.log_file, "error" if level == "error" else "warning" if level == "warn" else "info")(text)

    def snapshot(self, since: int = 0) -> dict:
        job = None
        job_id = self.job_id or (db.query("SELECT MAX(id) AS id FROM jobs")[0]["id"] or 0)
        if job_id:
            row = db.query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
            tasks = db.query("SELECT status, COUNT(*) AS n FROM job_tasks WHERE job_id = ? GROUP BY status", (job_id,))
            cards = db.query("SELECT status, COUNT(*) AS n FROM job_cards WHERE job_id = ? GROUP BY status", (job_id,))
            t = {r["status"]: r["n"] for r in tasks}
            c = {r["status"]: r["n"] for r in cards}
            tasks_total, cards_total = sum(t.values()), sum(c.values())
            cards_done = cards_total - c.get("pending", 0)
            # каждая задача считается как 10 карточек, пока не известно, сколько их на самом деле
            done = t.get("done", 0) * 10 + cards_done
            total = tasks_total * 10 + cards_total
            job = {
                "id": job_id, "status": row["status"], "params": json.loads(row["params"]), "created_at": row["created_at"],
                "tasks_total": tasks_total, "tasks_done": t.get("done", 0), "cards_total": cards_total,
                "cards_done": cards_done, "cards_error": c.get("error", 0), "found": row["found"], "added": row["added"],
                "percent": round(100 * done / total) if total else 0,
            }
        with self._lock:
            logs = [entry for entry in self._logs if entry["id"] > since]
        status = self.status if self.busy() else "idle"
        return {"status": status, "message": self.message, "current": self.current, "job": job, "logs": logs,
                "per_hour": len(self._opened), "resumable": bool(job and job["status"] in ("paused", "running") and status == "idle")}

    # ---------- вежливый режим ----------

    def checkpoint(self) -> None:
        """Точка, где сбор может встать на паузу или остановиться."""
        if self._stop.is_set():
            raise base.Stopped()
        if self._pause.is_set():
            self._resume.clear()
            while self._pause.is_set() and not self._stop.is_set():
                self._resume.wait(0.3)
            if self._stop.is_set():
                raise base.Stopped()
            self.status = "running"
            self.log("Продолжаю.")

    def sleep(self, low: float, high: float | None = None) -> None:
        end = time.time() + (random.uniform(low, high) if high is not None else low)
        while time.time() < end:
            self.checkpoint()
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def _polite_wait(self) -> None:
        limit = max(1, int(self.settings.get("cards_per_hour", 300)))
        now = time.time()
        while self._opened and now - self._opened[0] > 3600:
            self._opened.popleft()
        if len(self._opened) >= limit:
            wait = 3600 - (now - self._opened[0]) + 1
            self.log(f"Достигнут лимит {limit} страниц в час. Жду {int(wait // 60) + 1} мин.", "warn")
            self.message = f"Лимит {limit} страниц в час: продолжу автоматически"
            self.sleep(wait)
            self.message = ""
        if self._opened:
            self.sleep(float(self.settings.get("delay_min", 3)), float(self.settings.get("delay_max", 8)))
        self._opened.append(time.time())

    def wait_obstacle(self, cfg: dict, kind: str) -> None:
        """Капча или блокировка: останавливаемся и ждём человека. Ничего не обходим."""
        self.status = "captcha"
        self.message = CAPTCHA_MESSAGE if kind == "капча" else BLOCK_MESSAGE
        self.log(f"{cfg.get('title', '')}: {kind}. {self.message}", "warn")
        self._resume.clear()
        while not self._resume.is_set():
            if self._stop.is_set():
                raise base.Stopped()
            self._resume.wait(0.3)
        if self._stop.is_set():
            raise base.Stopped()
        self.status, self.message = "running", ""
        self.log("Продолжаю после проверки.")

    def open(self, cfg: dict, url: str) -> None:
        """Открывает страницу источника с паузой, лимитом и проверкой капчи."""
        self.checkpoint()
        for _attempt in range(6):
            self._polite_wait()
            self.checkpoint()
            try:
                response = self.page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                raise base.SourceError(f"страница не открылась: {str(exc).splitlines()[0]}") from exc
            obstacle = base.is_captcha(self.page, cfg)
            if not obstacle and response is not None and response.status in (403, 429):
                obstacle = "блокировка"
            if not obstacle:
                return
            self.wait_obstacle(cfg, obstacle)
            if self.page.url.split("#")[0] == url and not base.is_captcha(self.page, cfg):
                return  # после капчи сайт сам вернул на нужную страницу
        raise base.SourceError("страница так и не открылась после нескольких проверок")

    # ---------- сам сбор ----------

    def _run(self, job_id: int) -> None:
        browser = None
        final = "done"
        try:
            self.settings = db.get_settings()
            params = json.loads(db.query("SELECT params FROM jobs WHERE id = ?", (job_id,))[0]["params"])
            self.log(f"Сбор №{job_id}: {params['city']}, запросов: {len(params['queries'])}, "
                     f"источники: {', '.join(SOURCE_TITLES[s] for s in params['sources'])}")
            browser = Browser(self.settings)
            browser.start()
            self.page = browser.page
            tasks = db.query("SELECT * FROM job_tasks WHERE job_id = ? AND status != 'done' ORDER BY id", (job_id,))
            for task in tasks:
                self._run_task(job_id, params, dict(task))
            self.log("Сбор завершён.")
        except base.Stopped:
            final = "paused"
            self.log("Сбор остановлен. Его можно продолжить позже с того же места.")
        except BrowserError as exc:
            final = "paused"
            self.log(str(exc), "error")
        except Exception as exc:  # непредвиденная ошибка не должна терять прогресс
            final = "paused"
            self.log(f"Сбор прерван из-за ошибки: {exc}. Прогресс сохранён, сбор можно продолжить.", "error")
            self.log_file.exception("сбор прерван")
        finally:
            if browser:
                browser.stop()
            self.page = None
            db.execute("UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?", (final, db.now(), job_id))
            self.status, self.message, self.current = "idle", "", ""

    def _run_task(self, job_id: int, params: dict, task: dict) -> None:
        source = SOURCES[task["source"]]
        title = SOURCE_TITLES[task["source"]]
        query = f"{task['query']} {task['district']}".strip()
        self.current = f"{title}: {query}"
        if task["status"] == "pending":
            self.log(f"{title}: ищу «{query}»")
            try:
                for page_no, links in source.collect_links(self, params["city"], query, task["page"] + 1):
                    for url in links:
                        db.execute("INSERT OR IGNORE INTO job_cards(job_id, task_id, source, url) VALUES(?, ?, ?, ?)",
                                   (job_id, task["id"], task["source"], url))
                    db.execute("UPDATE job_tasks SET page = ? WHERE id = ?", (page_no, task["id"]))
                    self.log(f"{title}: «{query}», страница {page_no}: карточек {len(links)}")
            except base.SourceError as exc:
                self.log(f"{title}: «{query}»: {exc}", "error")
            db.execute("UPDATE job_tasks SET status = 'listed' WHERE id = ?", (task["id"],))
        cards = db.query("SELECT * FROM job_cards WHERE task_id = ? AND status = 'pending' ORDER BY id", (task["id"],))
        for card in cards:
            self.checkpoint()
            self._run_card(job_id, params, task, dict(card))
        db.execute("UPDATE job_tasks SET status = 'done' WHERE id = ?", (task["id"],))

    def _run_card(self, job_id: int, params: dict, task: dict, card: dict) -> None:
        source = SOURCES[card["source"]]
        key = CARD_KEYS[card["source"]]
        try:
            known = db.query("SELECT id FROM companies WHERE card_urls LIKE ?", (f'%"{key}": "{card["url"]}"%',))
            if known:
                db.execute("UPDATE job_cards SET status = 'skipped' WHERE id = ?", (card["id"],))
                return
            company = source.parse_card(self, card["url"])
            company.setdefault("city", params["city"])
            company.setdefault("niche", params["niche"])
            if task["district"] and not company.get("district"):
                company["district"] = task["district"]
            company_id, created = db.upsert_company(company, job_id, self.settings)
            db.execute("UPDATE jobs SET found = found + 1, added = added + ? WHERE id = ?", (1 if created else 0, job_id))
            self.log(f"{'＋' if created else '＝'} {company['name']}" + ("" if created else " (дубль, объединён)"))
            if params.get("enrich") and not company.get("enriched"):
                self._enrich(company_id, params)
            db.execute("UPDATE job_cards SET status = 'done' WHERE id = ?", (card["id"],))
        except base.Stopped:
            raise
        except Exception as exc:
            text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            db.execute("UPDATE job_cards SET status = 'error', error = ? WHERE id = ?", (text[:300], card["id"]))
            self.log(f"Ошибка на карточке {card['url']}: {text}", "error")

    def _enrich(self, company_id: int, params: dict) -> None:
        company = db.get_company(company_id)
        if company.get("enriched"):
            return
        updates: dict = {"enriched": 1}
        site = company.get("site") or ""
        if not site and params.get("find_sites"):
            try:
                site = yandex_search.find_site(self, company["name"], company.get("city") or params["city"])
            except base.SourceError as exc:
                self.log(f"Поиск сайта для «{company['name']}»: {exc}", "warn")
            if site:
                updates.update(site=site, site_found_by="search")
                self.log(f"   сайт найден через поиск: {site}")
        if site:
            result = site_check.check(site, timeout=int(self.settings.get("page_timeout", 45)))
            result.pop("title", None)
            for field in ("phones", "emails"):
                updates[field] = list(dict.fromkeys(company.get(field, []) + result.pop(field, [])))
            for field in ("telegram", "whatsapp", "max", "vk", "instagram", "booking"):
                value = result.pop(field, "")
                if value and not company.get(field):
                    updates[field] = value
            updates.update(result)
            if result["site_status"] == "down":
                self.log(f"   сайт {site} не открывается: {result['site_error']}", "warn")
        db.update_company(company_id, updates, self.settings)


collector = Collector()


def mark_interrupted_jobs() -> None:
    """После закрытия программы незавершённые сборы становятся «на паузе»."""
    db.execute("UPDATE jobs SET status = 'paused' WHERE status = 'running'")
