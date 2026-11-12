"""2ГИС: выдача по страницам и карточка компании."""
from __future__ import annotations

import re

import textutil
import variants
from sources import base

NAME = "twogis"

# Ищет в данных страницы (window.initialState) объект компании по её id.
STATE_JS = r"""
([stateVar, firmId]) => {
  const root = window[stateVar];
  if (!root) return null;
  let best = null, seen = 0;
  const walk = (node, depth) => {
    if (!node || typeof node !== 'object' || depth > 12 || seen > 200000) return;
    seen++;
    if (!Array.isArray(node) && node.name && node.id && String(node.id).split('_')[0] === firmId
        && (node.contact_groups || node.address_name || node.rubrics)) {
      if (!best || (node.contact_groups && !best.contact_groups)) best = node;
    }
    for (const key in node) walk(node[key], depth + 1);
  };
  try { walk(root, 0); } catch (e) {}
  return best ? JSON.parse(JSON.stringify(best)) : null;
}
"""

DAYS = [("Mon", "Пн"), ("Tue", "Вт"), ("Wed", "Ср"), ("Thu", "Чт"), ("Fri", "Пт"), ("Sat", "Сб"), ("Sun", "Вс")]


def format_schedule(schedule: dict | None) -> str:
    if not schedule:
        return ""
    if schedule.get("is_24x7"):
        return "Круглосуточно"
    groups: list[list] = []  # [первый день, последний день, часы]
    for key, title in DAYS:
        hours = ", ".join(f"{h.get('from', '')}–{h.get('to', '')}" for h in (schedule.get(key) or {}).get("working_hours", []))
        hours = hours or "выходной"
        if groups and groups[-1][2] == hours:
            groups[-1][1] = title
        else:
            groups.append([title, title, hours])
    return "; ".join(f"{a if a == b else a + '–' + b} {hours}" for a, b, hours in groups)


def parse_state_item(item: dict) -> dict:
    """Превращает объект компании из данных 2ГИС в поля базы."""
    company: dict = {
        "name": item.get("name") or "",
        "address": item.get("address_name") or "",
        "rubrics": [r.get("name", "") for r in item.get("rubrics") or []],
        "hours": format_schedule(item.get("schedule")),
        "branches": (item.get("org") or {}).get("branch_count") or 0,
        "phones": [], "emails": [],
    }
    reviews = item.get("reviews") or {}
    company["rating"] = reviews.get("general_rating") or reviews.get("org_rating") or 0
    company["reviews"] = reviews.get("general_review_count") or reviews.get("org_review_count") or 0
    for div in item.get("adm_div") or []:
        if div.get("type") == "district":
            company["district"] = div.get("name", "")
    for group in item.get("contact_groups") or []:
        for contact in group.get("contacts") or []:
            kind, value, text = contact.get("type", ""), contact.get("value") or "", contact.get("text") or ""
            url = contact.get("url") or value
            if kind == "phone":
                phone = textutil.norm_phone(value) or textutil.norm_phone(text)
                if phone:
                    base.add_contact(company, "phone", phone)
            elif kind == "email":
                base.add_contact(company, "email", value.lower())
            elif kind == "website":
                real = textutil.unwrap_redirect(url) if "link.2gis" in url else url
                site = real or text
                if "link.2gis" in site or not site:
                    site = text
                if site and textutil.is_company_site(site):
                    base.add_contact(company, "site", textutil.norm_site(site))
                else:
                    found, val = textutil.classify_link(site if "://" in site else "https://" + site)
                    if found:
                        base.add_contact(company, found, val)
            else:
                link = url if url.startswith("http") else ""
                if kind == "telegram" and not link and value:
                    link = "https://t.me/" + value.lstrip("@")
                if kind == "whatsapp" and not link and textutil.norm_phone(value):
                    link = "https://wa.me/" + textutil.norm_phone(value)
                found, val = textutil.classify_link(link)
                if found and found != "site":
                    base.add_contact(company, found, val)
    base.split_name(company)
    return company


def _slug(city: str) -> str:
    return variants.city_info(city).get("twogis", "")


def collect_links(session, city: str, query: str, start_page: int = 1):
    """Проходит страницы выдачи и отдаёт (номер страницы, список ссылок на карточки)."""
    cfg = base.source_config(NAME)
    slug = _slug(city)
    seen: set[str] = set()
    max_pages = int(session.settings.get("max_pages", 20))
    for page_no in range(start_page, max_pages + 1):
        if slug:
            url = base.build_url(cfg, "search_url", city=slug, query=query, page=page_no)
        else:
            url = base.build_url(cfg, "search_url_nocity", query=f"{query} {city}", page=page_no)
        session.open(cfg, url)
        page = session.page
        try:
            page.wait_for_selector(cfg["card_link"], timeout=8000)
        except Exception:
            pass
        hrefs = page.eval_on_selector_all(cfg["card_link"], "els => els.map(e => e.href)")
        links = []
        for href in hrefs:
            found = re.search(cfg["card_id_regex"], href)
            if not found or found.group(1) in seen:
                continue
            seen.add(found.group(1))
            key = "card_url" if slug else "card_url_nocity"
            links.append(base.build_url(cfg, key, city=slug, id=found.group(1)))
        if not links:
            return
        yield page_no, links


def parse_card(session, url: str) -> dict:
    cfg = base.source_config(NAME)
    session.open(cfg, url)
    page = session.page
    company = base.extract_card(page, cfg)
    firm_id = re.search(cfg["card_id_regex"], url)
    item = None
    if firm_id:
        try:
            item = page.evaluate(STATE_JS, [cfg.get("state_var", "initialState"), firm_id.group(1)])
        except Exception:
            item = None
    if item:
        from_state = parse_state_item(item)
        for key, value in company.items():  # данные страницы надёжнее вёрстки; вёрстка только дополняет
            if key in ("phones", "emails", "rubrics"):
                from_state[key] = list(dict.fromkeys((from_state.get(key) or []) + value))
            elif value and not from_state.get(key):
                from_state[key] = value
        company = from_state
    if not company.get("name"):
        raise base.SourceError("на странице не найдено название компании (проверьте селекторы 2ГИС)")
    company["card_urls"] = {"2gis": url}
    return company
