"""Общее для источников: адреса, проверка капчи, разбор карточки по селекторам."""
from __future__ import annotations

import re
from urllib.parse import quote

import config
import textutil


class Stopped(Exception):
    """Пользователь нажал «Стоп»."""


class SourceError(Exception):
    """Ошибка на странице: записываем в лог и идём дальше."""


def source_config(name: str) -> dict:
    return config.load_json_config("selectors.json")[name]


def build_url(cfg: dict, key: str, **values) -> str:
    values = {k: quote(str(v), safe="") if k in ("query", "city") else v for k, v in values.items()}
    return cfg[key].format(base=cfg["base_url"].rstrip("/"), **values)


def is_captcha(page, cfg: dict) -> str:
    """Возвращает описание препятствия (капча/блокировка) или пустую строку."""
    url = page.url.lower()
    if any(mark in url for mark in cfg.get("captcha_url", [])):
        return "капча"
    try:
        for selector in cfg.get("captcha_selectors", []):
            if page.query_selector(selector):
                return "капча"
        text = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 3000)")
    except Exception:
        return ""
    for mark in cfg.get("blocked_text", []):
        if mark.lower() in text.lower():
            return "блокировка"
    return ""


CARD_JS = r"""
(card) => {
  const first = (sels) => {
    for (const s of sels || []) {
      try {
        const el = document.querySelector(s);
        const text = el && (el.innerText || el.textContent || '').trim();
        if (text) return text;
      } catch (e) {}
    }
    return '';
  };
  const all = (sels) => {
    for (const s of sels || []) {
      try {
        const items = [...document.querySelectorAll(s)].map(e => (e.innerText || e.textContent || '').trim()).filter(Boolean);
        if (items.length) return items;
      } catch (e) {}
    }
    return [];
  };
  const links = (sels) => {
    const out = [];
    for (const s of sels || []) {
      try {
        for (const a of document.querySelectorAll(s)) out.push([a.href || '', (a.innerText || a.textContent || '').trim()]);
      } catch (e) {}
    }
    return out;
  };
  let scope = null;
  for (const s of (card.contacts_scope || 'body').split(',')) {
    try { scope = document.querySelector(s.trim()); } catch (e) {}
    if (scope) break;
  }
  scope = scope || document.body;
  return {
    name: first(card.name), address: first(card.address), district: first(card.district),
    rubrics: all(card.rubrics), rating: first(card.rating), reviews: first(card.reviews), hours: first(card.hours),
    site_links: links(card.site), phone_texts: all(card.phone_text),
    links: [...scope.querySelectorAll('a[href]')].map(a => [a.href, (a.innerText || '').trim()]),
    text: (scope.innerText || '').slice(0, 20000),
  };
}
"""


def _number(text: str, as_float: bool = False):
    text = (text or "").replace("\u00a0", " ")
    if as_float:
        found = re.search(r"\d+(?:[.,]\d+)?", text)
        return float(found.group(0).replace(",", ".")) if found else 0
    found = re.search(r"\d[\d ]*", text)
    return int(found.group(0).replace(" ", "")) if found else 0


def split_name(company: dict) -> None:
    """«Потолки, студия» → название «Потолки», а «студия» уходит в рубрики."""
    name = (company.get("name") or "").strip()
    if ", " in name:
        brand, extra = name.split(", ", 1)
        company["name"] = brand.strip()
        if extra.strip() and extra.strip() not in company.setdefault("rubrics", []):
            company["rubrics"].append(extra.strip())


def add_contact(company: dict, kind: str, value: str) -> None:
    if kind == "phone":
        if value not in company.setdefault("phones", []):
            company["phones"].append(value)
    elif kind == "email":
        if value not in company.setdefault("emails", []):
            company["emails"].append(value)
    elif kind in ("telegram", "whatsapp", "max", "vk", "instagram", "booking", "site"):
        company.setdefault(kind, value)


def extract_card(page, cfg: dict) -> dict:
    """Собирает карточку по селекторам из конфига + по ссылкам tel:/mailto:/t.me и т.п."""
    card = cfg["card"]
    for selector in card.get("ready", []):
        try:
            page.wait_for_selector(selector, timeout=8000)
            break
        except Exception:
            continue
    for selector in card.get("reveal_phone", []):
        try:
            button = page.query_selector(selector)
            if button:
                button.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            pass
    raw = page.evaluate(CARD_JS, card)
    ignore = [w.lower() for w in cfg.get("ignore_links", [])]
    company: dict = {
        "name": raw["name"].split("\n")[0].strip(),
        "address": re.sub(r"\s+", " ", raw["address"]),
        "district": raw["district"],
        "rubrics": [r for r in raw["rubrics"] if len(r) < 60][:8],
        "rating": _number(raw["rating"], as_float=True),
        "reviews": _number(raw["reviews"]),
        "hours": re.sub(r"\s+", " ", raw["hours"])[:200],
        "phones": [], "emails": [],
    }
    if company["rating"] > 5:
        company["rating"] = 0
    for href, text in raw["site_links"]:
        kind, value = textutil.classify_link(href)
        if kind != "site" and re.fullmatch(r"[\w\-.]+\.[a-zа-я]{2,10}", text.lower() or ""):
            kind, value = "site", textutil.norm_site(text.lower())
        if kind == "site" and not any(w in value for w in ignore):
            company["site"] = value
            break
    for href, _text in raw["links"]:
        kind, value = textutil.classify_link(href)
        if not kind or kind == "site":
            continue
        if kind not in ("phone", "email") and any(w in value.lower() for w in ignore):
            continue
        add_contact(company, kind, value)
    for text in raw["phone_texts"]:
        for phone in textutil.find_phones(text):
            add_contact(company, "phone", phone)
    for email in textutil.find_emails(raw["text"]):
        add_contact(company, "email", email)
    split_name(company)
    return company
