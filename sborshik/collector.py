"""Движок сбора: несколько окон браузера, очередь задач, паузы, капча, возобновление."""
from __future__ import annotations

import collections
import json
import queue
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import config
import db
from browser import Browser, BrowserError
from enrich import site_check
from sources import base, twogis, yandex_maps, yandex_search

SOURCES = {"twogis": twogis, "yandex_maps": yandex_maps, "yandex_search": yandex_search}
SOURCE_TITLES = {"twogis": "2ГИС", "yandex_maps": "Яндекс Карты", "yandex_search": "Поиск Яндекса"}
CARD_KEYS = {"twogis": "2gis", "yandex_maps": "yandex_maps", "yandex_search": "yandex_search"}
CAPTCHA_MESSAGE = "Решите капчу в окне браузера и нажмите «Продолжить»"
BLOCK_MESSAGE = "Сайт ограничил доступ. Подождите, проверьте страницу в окне браузера и нажмите «Продолжить»"


class Limiter:
    """Общий для всех окон одного источника счётчик страниц за час."""

    def __init__(self):
        self.lock = threading.Lock()
        self.opened: collections.deque = collections.deque()

    def reserve(self, limit: int) -> float:
        """Занимает место в часовом лимите. Возвращает 0 или сколько секунд ждать."""
        with self.lock:
            now = time.time()
            while self.opened and now - self.opened[0] > 3600:
                self.opened.popleft()
            if len(self.opened) >= limit:
                return 3600 - (now - self.opened[0]) + 1
            self.opened.append(now)
            return 0.0

    def count(self) -> int:
        with self.lock:
            return len(self.opened)


class Session:
    """Одно окно браузера. Источники работают только через него."""

    def __init__(self, owner: "Collector", source: str, slot: int):
        self.owner, self.source, self.slot = owner, source, slot
        self.settings = owner.settings
        self.name = f"{SOURCE_TITLES[source]}, окно {slot + 1}"
        self.browser: Browser | None = None
        self.page = None
        self._last_open = 0.0

    def start(self) -> None:
        self.browser = Browser(self.settings, profile=f"browser-profile-{self.source}-{self.slot}", slot=self.owner.next_slot())
        self.browser.start()
        self.page = self.browser.page

    def stop(self) -> None:
        if self.browser:
            self.browser.stop()
        self.browser = self.page = None

    def log(self, text: str, level: str = "info") -> None:
        self.owner.log(text, level)

    def checkpoint(self) -> None:
        self.owner.checkpoint()

    def sleep(self, low: float, high: float | None = None) -> None:
        end = time.time() + (random.uniform(low, high) if high is not None else low)
        while time.time() < end:
            self.checkpoint()
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def _polite_wait(self) -> None:
        limit = max(1, int(self.settings.get("cards_per_hour", 600)))
        limiter = self.owner.limiter(self.source)
        while True:
            wait = limiter.reserve(limit)
            if wait <= 0:
                break
            self.log(f"{SOURCE_TITLES[self.source]}: лимит {limit} страниц в час. Жду {int(wait // 60) + 1} мин.", "warn")
            self.sleep(min(wait, 120))
        # пауза считается от прошлого открытия: время на разбор страницы в неё входит
        pause = random.uniform(float(self.settings.get("delay_min", 2)), float(self.settings.get("delay_max", 5)))
        remaining = self._last_open + pause - time.time()
        if self._last_open and remaining > 0:
            self.sleep(remaining)
        self._last_open = time.time()

    def wait_obstacle(self, cfg: dict, kind: str) -> None:
        """Капча или блокировка: это окно останавливается и ждёт человека. Ничего не обходим."""
        message = CAPTCHA_MESSAGE if kind == "капча" else BLOCK_MESSAGE
        self.log(f"{self.name}: {kind}. {message}", "warn")
        seen = self.owner.resume_seq
        self.owner.obstacles[self.name] = message
        try:
            while self.owner.resume_seq == seen:
                if self.owner.stopping():
                    raise base.Stopped()
                time.sleep(0.3)
        finally:
            self.owner.obstacles.pop(self.name, None)
        self.log(f"{self.name}: продолжаю после проверки.")

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


class Collector:
    def __init__(self):
        self.log_file = config.setup_logging()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._logs: collections.deque = collections.deque(maxlen=800)
        self._log_id = 0
        self.resume_seq = 0
        self.obstacles: dict[str, str] = {}
        self.job_id = 0
        self.settings: dict = {}
        self._limiters: dict[str, Limiter] = {}
        self._claimed: set[int] = set()
        self._current: dict[str, str] = {}
        self._slots = 0
        self._failed = False
        self._enrich_q: queue.Queue = queue.Queue()
        self._queued: set[int] = set()
        self._pool: ThreadPoolExecutor | None = None

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
        niche = (params.get("niche") or queries[0]).strip()
        clean = {"city": city, "niche": niche, "queries": queries, "districts": [d for d in districts if d],
                 "sources": sources, "enrich": bool(params.get("enrich", True)),
                 "find_sites": bool(params.get("find_sites", True)), "base_id": db.ensure_base(niche, city)}
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
        self.obstacles.clear()
        self._claimed, self._queued, self._current = set(), set(), {}
        self._slots, self._failed, self.job_id = 0, False, job_id
        self._enrich_q = queue.Queue()
        self._thread = threading.Thread(target=self._run, args=(job_id,), daemon=True, name="collector")
        self._thread.start()

    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def status(self) -> str:
        if not self.busy():
            return "idle"
        if self._stop.is_set():
            return "stopping"
        if self.obstacles:
            return "captcha"
        return "paused" if self._pause.is_set() else "running"

    @property
    def message(self) -> str:
        items = list(self.obstacles.items())
        return f"{items[0][0]}: {items[0][1]}" if items else ""

    def pause(self) -> None:
        if self.busy() and not self._pause.is_set():
            self._pause.set()
            self.log("Пауза. Нажмите «Продолжить», чтобы идти дальше.")

    def resume(self) -> None:
        if self._pause.is_set():
            self.log("Продолжаю.")
        self._pause.clear()
        self.resume_seq += 1

    def stop(self) -> None:
        if self.busy():
            self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def limiter(self, source: str) -> Limiter:
        with self._lock:
            return self._limiters.setdefault(source, Limiter())

    def next_slot(self) -> int:
        with self._lock:
            self._slots += 1
            return self._slots - 1

    def checkpoint(self) -> None:
        """Точка, где окно может встать на паузу или остановиться."""
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.2)
        if self._stop.is_set():
            raise base.Stopped()

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
            per_hour = sum(limiter.count() for limiter in self._limiters.values())
        status = self.status
        return {"status": status, "message": self.message, "current": " · ".join(self._current.values()), "job": job,
                "logs": logs, "per_hour": per_hour, "windows": len(self._current), "sites_left": self._enrich_q.qsize(), "recheck_left": rechecker.left,
                "resumable": bool(job and job["status"] in ("paused", "running") and status == "idle")}

    # ---------- сам сбор ----------

    def _run(self, job_id: int) -> None:
        final = "done"
        try:
            self.settings = db.get_settings()
            params = json.loads(db.query("SELECT params FROM jobs WHERE id = ?", (job_id,))[0]["params"])
            params.setdefault("base_id", db.ensure_base(params["niche"], params["city"]))
            windows = min(3, max(1, int(self.settings.get("windows_per_source", 2))))
            self._pool = ThreadPoolExecutor(max_workers=min(12, max(1, int(self.settings.get("site_threads", 6)))))
            workers = []
            for source in params["sources"]:
                left = db.query("SELECT COUNT(*) AS n FROM job_tasks WHERE job_id = ? AND source = ? AND status != 'done'",
                                (job_id, source))[0]["n"]
                for slot in range(min(windows, left)):
                    workers.append(threading.Thread(target=self._source_worker, args=(job_id, params, source, slot), daemon=True))
            self.log(f"Сбор №{job_id}: {params['city']}, запросов: {len(params['queries'])}, окон браузера: {len(workers)}, "
                     f"источники: {', '.join(SOURCE_TITLES[s] for s in params['sources'])}")
            enricher = threading.Thread(target=self._enrich_worker, args=(params,), daemon=True)
            if params.get("enrich"):  # компании, чьи сайты не успели проверить до остановки
                for row in db.query("SELECT id FROM companies WHERE job_id = ? AND enriched = 0", (job_id,)):
                    self._queue_enrich(row["id"])
            enricher.start()
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            self._enrich_q.put(None)
            enricher.join()
            self._pool.shutdown(wait=True, cancel_futures=self._stop.is_set())
            if self._stop.is_set():
                final = "paused"
                self.log("Сбор остановлен. Его можно продолжить позже с того же места.")
            elif self._failed:
                final = "paused"
            else:
                self.log("Сбор завершён.")
        except Exception as exc:  # непредвиденная ошибка не должна терять прогресс
            final = "paused"
            self._stop.set()
            self.log(f"Сбор прерван из-за ошибки: {exc}. Прогресс сохранён, сбор можно продолжить.", "error")
            self.log_file.exception("сбор прерван")
        finally:
            db.execute("UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?", (final, db.now(), job_id))
            self._current = {}
            self.obstacles.clear()

    def _claim_task(self, job_id: int, source: str) -> dict | None:
        with self._lock:
            rows = db.query("SELECT * FROM job_tasks WHERE job_id = ? AND source = ? AND status != 'done' ORDER BY id", (job_id, source))
            for row in rows:
                if row["id"] not in self._claimed:
                    self._claimed.add(row["id"])
                    return dict(row)
        return None

    def _source_worker(self, job_id: int, params: dict, source: str, slot: int) -> None:
        session = Session(self, source, slot)
        try:
            session.start()
            while True:
                task = self._claim_task(job_id, source)
                if not task:
                    break
                self._run_task(session, job_id, params, task)
        except base.Stopped:
            pass
        except BrowserError as exc:
            self._failed = True
            self.log(str(exc), "error")
        except Exception as exc:
            self._failed = True
            self.log(f"{session.name}: окно остановилось из-за ошибки: {exc}", "error")
            self.log_file.exception("ошибка окна")
        finally:
            self._current.pop(session.name, None)
            session.stop()

    def _run_task(self, session: Session, job_id: int, params: dict, task: dict) -> None:
        source = SOURCES[task["source"]]
        title = SOURCE_TITLES[task["source"]]
        query = f"{task['query']} {task['district']}".strip()
        self._current[session.name] = f"{title}: {query}"
        if task["status"] == "pending":
            self.log(f"{title}: ищу «{query}»")
            try:
                for page_no, links in source.collect_links(session, params["city"], query, task["page"] + 1):
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
            session.checkpoint()
            self._run_card(session, job_id, params, task, dict(card))
        db.execute("UPDATE job_tasks SET status = 'done' WHERE id = ?", (task["id"],))

    def _run_card(self, session: Session, job_id: int, params: dict, task: dict, card: dict) -> None:
        source = SOURCES[card["source"]]
        key = CARD_KEYS[card["source"]]
        try:
            known = db.query("SELECT id FROM companies WHERE card_urls LIKE ?", (f'%"{key}": "{card["url"]}"%',))
            if known:
                db.execute("UPDATE job_cards SET status = 'skipped' WHERE id = ?", (card["id"],))
                return
            company = source.parse_card(session, card["url"])
            company.setdefault("city", params["city"])
            company.setdefault("niche", params["niche"])
            if task["district"] and not company.get("district"):
                company["district"] = task["district"]
            company_id, created = db.upsert_company(company, job_id, self.settings, params.get("base_id", 0))
            db.execute("UPDATE jobs SET found = found + 1, added = added + ? WHERE id = ?", (1 if created else 0, job_id))
            self.log(f"{'＋' if created else '＝'} {company['name']}" + ("" if created else " (дубль, объединён)"))
            if params.get("enrich") and not company.get("enriched"):
                self._queue_enrich(company_id)
            db.execute("UPDATE job_cards SET status = 'done' WHERE id = ?", (card["id"],))
        except base.Stopped:
            raise
        except Exception as exc:
            text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            db.execute("UPDATE job_cards SET status = 'error', error = ? WHERE id = ?", (text[:300], card["id"]))
            self.log(f"Ошибка на карточке {card['url']}: {text}", "error")

    # ---------- проверка сайтов (идёт параллельно со сбором) ----------

    def _queue_enrich(self, company_id: int) -> None:
        with self._lock:
            if company_id in self._queued:
                return
            self._queued.add(company_id)
        self._enrich_q.put(company_id)

    def _enrich_worker(self, params: dict) -> None:
        """Разбирает очередь компаний: ищет сайт через поиск (своё окно) и отдаёт сайты на проверку."""
        session: Session | None = None
        try:
            while True:
                try:
                    company_id = self._enrich_q.get(timeout=0.3)
                except queue.Empty:
                    if self._stop.is_set():
                        return
                    continue
                if company_id is None or self._stop.is_set():
                    return
                company = db.get_company(company_id)
                if company.get("enriched"):
                    continue
                site, found_by = company.get("site") or "", ""
                if not site and params.get("find_sites"):
                    try:
                        if session is None:
                            session = Session(self, "yandex_search", 9)
                            session.name = "Поиск сайтов"
                            session.start()
                        site = yandex_search.find_site(session, company["name"], company.get("city") or params["city"])
                    except base.SourceError as exc:
                        self.log(f"Поиск сайта для «{company['name']}»: {exc}", "warn")
                    except BrowserError as exc:
                        self.log(f"Поиск сайтов отключён: {exc}", "error")
                        params["find_sites"] = False
                    if site:
                        found_by = "search"
                        self.log(f"   {company['name']}: сайт найден через поиск: {site}")
                self._pool.submit(self._check_site, company_id, company["name"], site, found_by)
        except base.Stopped:
            pass
        finally:
            if session:
                session.stop()

    def _check_site(self, company_id: int, name: str, site: str, found_by: str) -> None:
        try:
            updates: dict = {"enriched": 1}
            if site:
                result = site_check.check(site, timeout=int(self.settings.get("page_timeout", 45)))
                result.pop("title", None)
                updates.update(result)
                if found_by:
                    updates.update(site=site, site_found_by=found_by)
                if result["site_status"] == "down":
                    self.log(f"   {name}: сайт {site} не открывается: {result['site_error']}", "warn")
            db.enrich_company(company_id, updates, self.settings)
        except Exception as exc:
            self.log(f"Проверка сайта «{name}»: {exc}", "error")
            self.log_file.exception("ошибка проверки сайта")


class Rechecker:
    """Повторная проверка сайтов у уже собранных компаний (без браузера)."""

    def __init__(self):
        self.left = 0
        self._lock = threading.Lock()

    def start(self, base_id: int = 0) -> int:
        if self.left:
            raise RuntimeError("Перепроверка уже идёт.")
        where, args = ("AND base_id = ?", (base_id,)) if base_id else ("", ())
        rows = db.query(f"SELECT id, name, site FROM companies WHERE site != '' {where}", args)
        if not rows:
            return 0
        settings = db.get_settings()
        self.left = len(rows)
        collector.log(f"Перепроверка сайтов: {len(rows)}")
        pool = ThreadPoolExecutor(max_workers=min(12, max(1, int(settings.get("site_threads", 6)))))

        def one(row) -> None:
            try:
                result = site_check.check(row["site"], timeout=int(settings.get("page_timeout", 45)))
                result.pop("title", None)
                db.enrich_company(row["id"], dict(result, enriched=1), settings)
            except Exception as exc:
                collector.log(f"Проверка сайта «{row['name']}»: {exc}", "error")
            finally:
                with self._lock:
                    self.left -= 1
                    if self.left == 0:
                        collector.log("Перепроверка сайтов завершена.")

        for row in rows:
            pool.submit(one, row)
        pool.shutdown(wait=False)
        return len(rows)


collector = Collector()
rechecker = Rechecker()


def mark_interrupted_jobs() -> None:
    """После закрытия программы незавершённые сборы становятся «на паузе»."""
    db.execute("UPDATE jobs SET status = 'paused' WHERE status = 'running'")
