"""Поиск Яндекса: источник сайтов компаний и поиск сайта по названию."""
from __future__ import annotations

import textutil
from enrich import site_check
from sources import base

NAME = "yandex_search"

RESULTS_JS = r"""
(cfg) => [...document.querySelectorAll(cfg.result)].map(item => {
  const pick = (sel) => { try { const el = item.querySelector(sel); return el ? (el.innerText || '').trim() : ''; } catch (e) { return ''; } };
  let href = '';
  try { const a = item.querySelector(cfg.result_link); href = a ? a.href : ''; } catch (e) {}
  return { href, title: pick(cfg.result_title), snippet: pick(cfg.result_snippet) };
}).filter(r => r.href)
"""


def search(session, query: str, page_no: int = 1) -> list[dict]:
    cfg = base.source_config(NAME)
    session.open(cfg, base.build_url(cfg, "search_url", query=query, page0=page_no - 1))
    try:
        session.page.wait_for_selector(cfg["result"], timeout=8000)
    except Exception:
        return []
    results = []
    for item in session.page.evaluate(RESULTS_JS, cfg):
        href = textutil.unwrap_redirect(item["href"])
        if href and textutil.is_company_site(href):
            results.append({"url": textutil.norm_site(href), "title": item["title"], "snippet": item["snippet"]})
    return results


def matches(name: str, city: str, result: dict) -> bool:
    """Сайт берём, только если в заголовке/описании есть и название, и город."""
    text = f"{result['title']} {result['snippet']}".lower().replace("ё", "е")
    tokens = textutil.name_tokens(name)
    if not tokens or not all(token in text for token in tokens):
        return False
    city_norm = city.lower().replace("ё", "е")
    stem = city_norm[:-1] if len(city_norm) > 4 else city_norm  # «Казань» → «казан» (в Казани)
    return stem in text


def find_site(session, name: str, city: str) -> str:
    for result in search(session, f"{name} {city}"):
        if matches(name, city, result):
            return result["url"]
    return ""


def collect_links(session, city: str, query: str, start_page: int = 1):
    cfg = base.source_config(NAME)
    seen: set[str] = set()
    max_pages = min(int(cfg.get("max_pages", 5)), int(session.settings.get("max_pages", 20)))
    for page_no in range(start_page, max_pages + 1):
        links = [r["url"] for r in search(session, f"{query} {city}", page_no) if r["url"] not in seen]
        seen.update(links)
        if not links:
            return
        yield page_no, links


def parse_card(session, url: str) -> dict:
    """«Карточка» здесь — сам сайт компании: открываем его и собираем контакты."""
    result = site_check.check(url, timeout=int(session.settings.get("page_timeout", 45)))
    if result["site_status"] == "down":
        raise base.SourceError(f"сайт не открылся: {result['site_error']}")
    name = (result.pop("title", "") or "").split("|")[0].split(" — ")[0].split(" - ")[0].strip()
    company = {"name": name[:80] or textutil.domain_of(url), "site": url, "site_found_by": "search", "enriched": 1}
    company.update({k: v for k, v in result.items() if v})
    company["card_urls"] = {"yandex_search": url}
    return company
