"""Автосегменты и пометка «не мой клиент»."""
from __future__ import annotations

import datetime as dt

STATUSES = [
    ("new", "Не писал"), ("written", "Написал"), ("read", "Прочитал"), ("replied", "Ответил"),
    ("interest", "Интерес"), ("client", "Клиент"), ("refused", "Отказ"), ("silent", "Не отвечает"),
]
STATUS_NAMES = dict(STATUSES)


def check_not_my_client(company: dict, settings: dict) -> str:
    """Причина, по которой компания не подходит, или пустая строка."""
    haystack = f"{company.get('name', '')} {' '.join(company.get('rubrics') or [])}".lower().replace("ё", "е")
    for word in settings.get("stop_words") or []:
        word = word.strip().lower().replace("ё", "е")
        if word and word in haystack:
            return f"стоп-слово «{word}»"
    branches = int(company.get("branches") or 0)
    if branches >= int(settings.get("network_branches") or 5):
        return f"сеть: {branches} филиалов"
    return ""


def compute(company: dict, settings: dict) -> dict:
    """Возвращает segment, segment_reason и список всех найденных причин."""
    reasons: list[tuple[str, str]] = []
    site = company.get("site") or ""
    reviews = int(company.get("reviews") or 0)
    year = int(company.get("site_year") or 0)
    this_year = dt.date.today().year

    if site and company.get("site_status") == "down":
        reasons.append(("сайт не открывается", f"Сайт {site} не открывается: заявки с него не доходят"))
    if not site:
        reasons.append(("нет сайта", "Нет сайта: клиенты находят компанию только через карты"))
    if site and company.get("site_status") == "ok":
        if not company.get("site_ssl"):
            reasons.append(("сайт без SSL", "Сайт без защищённого соединения: браузер пишет «Не защищено»"))
        if not company.get("site_mobile"):
            reasons.append(("нет мобильной версии", "Сайт не адаптирован под телефон"))
        if not company.get("site_form") and not company.get("site_calc"):
            reasons.append(("сайт без заявки", "На сайте нет формы заявки и калькулятора"))
        if year and this_year - year >= int(settings.get("old_site_years") or 3):
            reasons.append(("сайт устарел", f"В подвале сайта стоит {year} год: сайт давно не обновляли"))
    if not company.get("telegram") and not company.get("whatsapp") and not company.get("max"):
        reasons.append(("нет мессенджеров", "Нет Telegram и WhatsApp: написать можно только по телефону"))
    if company.get("booking"):
        reasons.append(("есть онлайн-запись", f"Уже есть онлайн-запись ({company['booking']})"))
    else:
        reasons.append(("нет онлайн-записи", "Нет онлайн-записи: записаться можно только звонком"))

    many = reviews >= int(settings.get("many_reviews") or 50)
    if many:
        reasons.append(("много отзывов", f"{reviews} отзывов: живой бизнес с потоком клиентов"))

    nmc = check_not_my_client(company, settings)
    if nmc:
        segment, reason = "не мой клиент", nmc
    else:
        segment, reason = reasons[0]
    return {
        "segment": segment,
        "segment_reason": reason,
        "reasons": [r[1] for r in reasons],
        "tags": [r[0] for r in reasons],
        "not_my_client": 1 if nmc else 0,
        "nmc_reason": nmc,
    }
