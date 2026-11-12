"""Яндекс Карты: список организаций (с прокруткой) и карточка."""
from __future__ import annotations

import re

from sources import base

NAME = "yandex_maps"


def _links(page, cfg: dict, seen: set[str]) -> list[str]:
    links = []
    for href in page.eval_on_selector_all(cfg["card_link"], "els => els.map(e => e.href)"):
        found = re.search(cfg["card_id_regex"], href)
        if found and found.group(1) not in seen:
            seen.add(found.group(1))
            links.append(base.build_url(cfg, "card_url", id=found.group(1)))
    return links


def collect_links(session, city: str, query: str, start_page: int = 1):
    """У Яндекс Карт одна «страница» с подгрузкой: прокручиваем список до конца.
    Каждая порция новых карточек отдаётся как очередная страница."""
    cfg = base.source_config(NAME)
    if start_page > 1:
        return  # список уже был собран до конца в прошлый раз
    session.open(cfg, base.build_url(cfg, "search_url", query=f"{query} {city}"))
    page = session.page
    try:
        page.wait_for_selector(cfg["card_link"], timeout=10000)
    except Exception:
        pass
    seen: set[str] = set()
    idle = 0
    for step in range(1, int(cfg.get("max_scrolls", 60)) + 1):
        obstacle = base.is_captcha(page, cfg)
        if obstacle:
            session.wait_obstacle(cfg, obstacle)
        links = _links(page, cfg, seen)
        if links:
            idle = 0
            yield step, links
        else:
            idle += 1
        at_end = cfg.get("list_end") and page.query_selector(cfg["list_end"])
        if idle >= 3 or (at_end and not links):
            return
        page.evaluate(
            "(sel) => { const box = document.querySelector(sel); if (box) box.scrollTop = box.scrollHeight;"
            " else window.scrollTo(0, document.body.scrollHeight); }",
            cfg.get("list_scroll", ""),
        )
        session.sleep(1.5, 3.0)


def parse_card(session, url: str) -> dict:
    cfg = base.source_config(NAME)
    session.open(cfg, url)
    company = base.extract_card(session.page, cfg)
    if not company.get("name"):
        raise base.SourceError("на странице не найдено название компании (проверьте селекторы Яндекс Карт)")
    company["card_urls"] = {"yandex_maps": url}
    return company
