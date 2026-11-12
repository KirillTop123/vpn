"""Проблемы компании, автосегмент, «не мой клиент» и фразы для сообщений."""
from __future__ import annotations

import re

import config
import textutil

STATUSES = [
    ("new", "Не писал"), ("written", "Написал"), ("read", "Прочитал"), ("replied", "Ответил"),
    ("interest", "Интерес"), ("client", "Клиент"), ("refused", "Отказ"), ("silent", "Не отвечает"),
]
STATUS_NAMES = dict(STATUSES)

# От самой сильной проблемы к самой слабой: первая становится сегментом компании.
PRIORITY = [
    "сайт не открывается", "нет сайта", "сайт устарел", "нет мобильной версии", "простой сайт", "сайт без SSL",
    "сайт без заявки", "нет обратной связи", "сайт медленный", "нет калькулятора", "нет цен", "одностраничный сайт",
    "телефон не кликается", "нет мессенджеров на сайте", "нет примеров работ", "форма без политики", "нет счётчика",
    "нет мессенджеров", "бесплатный домен", "нет телефона на сайте", "мало текста", "нет отзывов на сайте",
    "нет перехода на https", "небезопасное содержимое", "нет описания для поиска", "нет заголовка страницы",
    "нет главного заголовка", "нет превью ссылки", "нет значка сайта", "почта на бесплатном домене",
    "низкий рейтинг", "мало отзывов", "нет онлайн-записи", "нет часов работы", "нет соцсетей", "нет почты",
]
NOT_PROBLEMS = ("есть онлайн-запись", "много отзывов")  # наблюдения, а не проблемы
SOURCE_NAMES = {"2gis": "2ГИС", "yandex_maps": "Яндекс Карт", "yandex_search": "поиска"}


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


def find_problems(company: dict, settings: dict) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    site = company.get("site") or ""
    reviews = int(company.get("reviews") or 0)
    rating = float(company.get("rating") or 0)
    if site and company.get("site_status") == "down":
        found.append(("сайт не открывается", f"Сайт {textutil.domain_of(site)} не открывается: заявки с него не доходят"))
    if not site:
        found.append(("нет сайта", "Нет сайта: клиенты находят компанию только через карты"))
    if site and company.get("site_status") == "ok":
        if not company.get("site_ssl"):
            found.append(("сайт без SSL", "Сайт без защищённого соединения: браузер пишет «Не защищено»"))
        if not company.get("site_mobile"):
            found.append(("нет мобильной версии", "Сайт не подстраивается под телефон"))
        if not company.get("site_form") and not company.get("site_calc"):
            found.append(("сайт без заявки", "На сайте нет формы заявки и калькулятора"))
        found += [(tag, text) for tag, text in company.get("site_issues") or []]
    if not company.get("telegram") and not company.get("whatsapp") and not company.get("max"):
        found.append(("нет мессенджеров", "Нет Telegram и WhatsApp: написать можно только по телефону"))
    if not company.get("booking"):
        found.append(("нет онлайн-записи", "Нет онлайн-записи: записаться можно только звонком"))
    if rating and reviews >= 5 and rating < float(settings.get("low_rating") or 4.0):
        found.append(("низкий рейтинг", f"Рейтинг {rating} при {reviews} отзывах: клиенты выбирают соседей"))
    if reviews < int(settings.get("few_reviews") or 5):
        found.append(("мало отзывов", f"Отзывов на картах: {reviews}. В выдаче компания ниже конкурентов"))
    if not company.get("hours"):
        found.append(("нет часов работы", "В карточке не указаны часы работы"))
    if not company.get("vk") and not company.get("instagram") and not company.get("telegram"):
        found.append(("нет соцсетей", "Нет ни одной соцсети: негде посмотреть работы"))
    if not company.get("emails"):
        found.append(("нет почты", "Не указана почта"))
    if company.get("booking"):
        found.append(("есть онлайн-запись", f"Уже есть онлайн-запись ({company['booking']})"))
    if reviews >= int(settings.get("many_reviews") or 50):
        found.append(("много отзывов", f"{reviews} отзывов: живой бизнес с потоком клиентов"))
    seen, unique = set(), []
    for tag, text in found:
        if tag not in seen:
            seen.add(tag)
            unique.append((tag, text))
    order = {tag: index for index, tag in enumerate(PRIORITY)}
    unique.sort(key=lambda item: (item[0] in NOT_PROBLEMS, order.get(item[0], len(PRIORITY))))
    return unique


def compute(company: dict, settings: dict) -> dict:
    """Возвращает segment, segment_reason и список всех найденных проблем."""
    problems = find_problems(company, settings)
    nmc = check_not_my_client(company, settings)
    segment, reason = ("не мой клиент", nmc) if nmc else problems[0]
    return {
        "segment": segment, "segment_reason": reason,
        "reasons": [text for _tag, text in problems], "tags": [tag for tag, _text in problems],
        "not_my_client": 1 if nmc else 0, "nmc_reason": nmc,
    }


def _fill(text: str, values: dict) -> str:
    return re.sub(r"\{([а-яё_]+)\}", lambda m: str(values.get(m.group(1).lower(), m.group(0))), text, flags=re.I)


def pitch(company: dict, settings: dict, base: dict | None = None) -> dict:
    """Готовые куски сообщения под конкретную компанию: кто пишет, зацепка, проблема, предложение."""
    phrases = config.load_json_config("pitches.json")
    tags, reasons = company.get("tags") or [], company.get("reasons") or []
    reviews, rating = int(company.get("reviews") or 0), company.get("rating") or 0
    source = next((SOURCE_NAMES[k] for k in ("2gis", "yandex_maps", "yandex_search") if k in (company.get("card_urls") or {})), "карт")
    main_tag = next((t for t in tags if t not in NOT_PROBLEMS), "")
    main_reason = reasons[tags.index(main_tag)] if main_tag else ""
    details = main_reason.split(": ", 1)[1] if ": " in main_reason else main_reason
    values = {"сайт": textutil.domain_of(company.get("site") or ""), "источник": source, "название": company.get("name", ""),
              "отзывы": reviews, "рейтинг": rating, "детали": details, "город": company.get("city", ""), "ниша": company.get("niche", "")}
    entry = phrases.get(main_tag) or {}
    problem = _fill(entry.get("problem", ""), values) or (main_reason + "." if main_reason else "")
    offer = _fill(entry.get("offer", "") or phrases.get("_default_offer", ""), values)
    hook = ""  # хвалим отзывы, только если они действительно есть
    if reviews >= int(settings.get("many_reviews") or 50) and float(rating or 0) >= 4.3:
        hook = _fill(phrases.get("_hook_many_reviews", ""), values)
    name = (settings.get("my_name") or "").strip()
    intro = _fill(((base or {}).get("intro") or "").strip(), values)
    parts = [f"Меня зовут {name}" if name else "", intro]
    who = ", ".join(p for p in parts if p)
    who = (who[:1].upper() + who[1:] + ". ") if who else ""
    return {"представление": who, "зацепка": hook, "проблема": problem, "предложение": offer,
            "проблемы": " ".join(r.rstrip(".") + "." for r, t in zip(reasons, tags) if t not in NOT_PROBLEMS)[:600]}
