"""Нормализация телефонов, сайтов и разбор ссылок на контакты."""
from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, unquote, urlparse

PHONE_RE = re.compile(r"(?<![\d\w])(?:\+7|8|7)[\s\-(]{0,3}\d{3}[\s\-)]{0,3}\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)")
EMAIL_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.[a-zA-Z]{2,10}")
BAD_EMAIL_TAILS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")
BAD_EMAIL_HOSTS = ("example.com", "example.ru", "domain.ru", "sentry.io", "wixpress.com", "mail.com.ru")

# Домены, которые не считаются «сайтом компании»
NOT_A_SITE = (
    "vk.com", "vk.ru", "vk.me", "t.me", "telegram.me", "wa.me", "whatsapp.com", "instagram.com", "max.ru",
    "ok.ru", "youtube.com", "youtu.be", "rutube.ru", "dzen.ru", "facebook.com", "tiktok.com", "viber.com",
    "2gis.ru", "2gis.com", "yandex.ru", "yandex.com", "ya.ru", "google.com", "google.ru", "avito.ru",
    "yclients.com", "dikidi.net", "dikidi.ru", "dikidi.app", "taplink.cc", "taplink.ws", "zoon.ru", "yell.ru",
    "flamp.ru", "profi.ru", "uslugi.yandex.ru", "youdo.com", "hh.ru", "wikipedia.org", "otzovik.com",
    "irecommend.ru", "tripadvisor.ru", "rusprofile.ru", "list-org.com", "sbis.ru", "orgpage.ru", "spr.ru",
    "blizko.ru", "pulscen.ru", "tiu.ru", "drom.ru", "auto.ru", "cataloxy.ru", "jsprav.ru", "altegio.com",
)

BOOKING_SERVICES = {
    "yclients.com": "YClients", "dikidi.net": "DIKIDI", "dikidi.ru": "DIKIDI", "dikidi.app": "DIKIDI",
    "altegio.com": "Altegio", "alteg.io": "Altegio", "sonline.su": "Sonline", "bukza.com": "Bukza",
    "easyweek.ru": "EasyWeek", "easyweek.io": "EasyWeek", "arnica.pro": "Арника", "profsalon.org": "Профсалон",
    "booking.medflex.ru": "МедФлекс", "prodoctorov.ru": "ПроДокторов", "napopravku.ru": "НаПоправку",
    "bookform.ru": "Bookform", "rubitime.ru": "Rubitime", "zapisi.online": "Записи.онлайн", "n-zapis.ru": "N-запись",
}


def norm_phone(raw: str) -> str:
    """'+7 (843) 123-45-67' -> '78431234567'. Пустая строка, если это не телефон."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    return ""


def pretty_phone(norm: str) -> str:
    if len(norm) == 11:
        return f"+{norm[0]} {norm[1:4]} {norm[4:7]}-{norm[7:9]}-{norm[9:]}"
    return norm


def find_phones(text: str) -> list[str]:
    out: list[str] = []
    for match in PHONE_RE.findall(text or ""):
        phone = norm_phone(match)
        if phone and phone not in out:
            out.append(phone)
    return out


def find_emails(text: str) -> list[str]:
    out: list[str] = []
    for match in EMAIL_RE.findall(text or ""):
        email = match.lower().strip(".")
        if email.endswith(BAD_EMAIL_TAILS) or email.split("@")[1] in BAD_EMAIL_HOSTS:
            continue
        if email not in out:
            out.append(email)
    return out


def domain_of(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _host_in(host: str, domains) -> str:
    for dom in domains:
        if host == dom or host.endswith("." + dom):
            return dom
    return ""


def is_company_site(url: str) -> bool:
    host = domain_of(url)
    return bool(host) and "." in host and not _host_in(host, NOT_A_SITE)


def norm_site(url: str) -> str:
    """Приводит сайт к виду 'https://domain.ru' (схему оставляет, если была)."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = domain_of(url)
    try:
        port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    except ValueError:
        port = ""
    return f"{parsed.scheme}://{host}{port}" if host else ""


def booking_service(url: str) -> str:
    return BOOKING_SERVICES.get(_host_in(domain_of(url), BOOKING_SERVICES), "")


def unwrap_redirect(url: str) -> str:
    """Разворачивает ссылки-обёртки (link.2gis.ru, vk.com/away.php и т.п.)."""
    host = domain_of(url)
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if host.startswith("link.2gis."):
        for part in parsed.path.split("/"):
            if len(part) < 16:
                continue
            try:
                decoded = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8", "ignore")
            except (ValueError, TypeError):
                continue
            found = re.search(r"https?://[^\s\"'<>]+", decoded)
            if found:
                return found.group(0)
        return ""
    query = parse_qs(parsed.query)
    for key in ("to", "url", "u", "target"):
        if key in query and query[key][0].startswith("http") and ("away" in parsed.path or "redirect" in parsed.path):
            return unquote(query[key][0])
    return url


def classify_link(href: str) -> tuple[str, str]:
    """Возвращает (тип, значение) для ссылки: phone, email, telegram, whatsapp,
    max, vk, instagram, booking, site или ('', '')."""
    href = (href or "").strip()
    low = href.lower()
    if low.startswith("tel:"):
        phone = norm_phone(unquote(href[4:]))
        return ("phone", phone) if phone else ("", "")
    if low.startswith("mailto:"):
        emails = find_emails(unquote(href[7:]))
        return ("email", emails[0]) if emails else ("", "")
    if low.startswith("tg://"):
        domain = parse_qs(urlparse(href).query).get("domain", [""])[0]
        return ("telegram", f"https://t.me/{domain}") if domain else ("", "")
    if low.startswith("whatsapp://"):
        phone = norm_phone(parse_qs(urlparse(href).query).get("phone", [""])[0])
        return ("whatsapp", f"https://wa.me/{phone}") if phone else ("", "")
    if not low.startswith("http"):
        return "", ""
    href = unwrap_redirect(href)
    if not href:
        return "", ""
    host = domain_of(href)
    path = urlparse(href).path.strip("/")
    if host in ("t.me", "telegram.me") and path and not path.startswith(("share", "joinchat/share")):
        return "telegram", f"https://t.me/{path}"
    if host in ("wa.me", "api.whatsapp.com", "web.whatsapp.com", "chat.whatsapp.com"):
        phone = norm_phone(path) or norm_phone(parse_qs(urlparse(href).query).get("phone", [""])[0])
        return ("whatsapp", f"https://wa.me/{phone}") if phone else ("whatsapp", href)
    if host == "max.ru" and path:
        return "max", f"https://max.ru/{path}"
    if host in ("vk.com", "vk.ru", "m.vk.com") and path and not path.startswith(("share", "away", "js", "rtrg", "widget")):
        return "vk", f"https://vk.com/{path}"
    if host in ("instagram.com", "instagr.am") and path:
        return "instagram", f"https://instagram.com/{path.split('/')[0]}"
    service = booking_service(href)
    if service:
        return "booking", service
    if is_company_site(href):
        return "site", norm_site(href)
    return "", ""


def norm_name(name: str) -> str:
    text = (name or "").lower().replace("ё", "е")
    text = re.sub(r"\b(ооо|ип|зао|оао|ао|пао|студия|компания|салон|центр|магазин)\b", " ", text)
    return re.sub(r"[^a-zа-я0-9]+", "", text)


def norm_address(address: str) -> str:
    text = (address or "").lower().replace("ё", "е")
    text = re.sub(r"\b(улица|ул|проспект|пр-кт|пр|дом|д|переулок|пер|шоссе|ш|г|город|этаж|офис|оф)\b\.?", " ", text)
    return re.sub(r"[^a-zа-я0-9]+", "", text)


def name_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-zа-я0-9]+", (name or "").lower().replace("ё", "е"))
    skip = {"ооо", "ип", "студия", "компания", "салон", "центр", "магазин", "и", "на", "в", "the"}
    return [w for w in words if len(w) >= 3 and w not in skip]
