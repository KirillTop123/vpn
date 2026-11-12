"""Проверка сайта компании: открывается ли, SSL, формы, запись, чат, контакты."""
from __future__ import annotations

import datetime as dt
import html as html_lib
import ipaddress
import os
import re
import socket
import ssl
from urllib.parse import urljoin, urlparse

import httpx

import textutil

USER_AGENT = "Mozilla/5.0 (compatible; SborshikBaz/1.0; desktop site checker)"
CALC_RE = re.compile(r"калькулятор|рассчитать стоимость|расч[её]т стоимости|рассчитать цену|calculator|marquiz|quiz", re.I)
FORM_TEXT_RE = re.compile(r"оставить заявку|заказать звонок|обратный звонок|перезвоните мне|оставьте заявку|получить консультацию", re.I)
FORM_RE = re.compile(r"<form\b.*?</form>", re.I | re.S)
FORM_FIELD_RE = re.compile(r"type=[\"']?tel|name=[\"']?[\w\-\[\]]*(phone|tel|telefon)|<textarea", re.I)
BOOKING_TEXT_RE = re.compile(r"онлайн[\s\-]запис|записаться онлайн|online[\s\-]?booking", re.I)
CHAT_RE = re.compile(
    r"jivosite|jivo\.ru|code\.jivo|b24-widget|bitrix24[^\"']*site_button|tawk\.to|carrotquest|talk-me\.ru|livetex|"
    r"chatra|callibri|envybox|leadback|venyoo|redhelper|me-talk|wazzup|chaport|tidio|crisp\.chat|verbox|"
    r"widget\.yandex\.ru/messenger|livechatinc|usedesk|chat2desk", re.I)
VIEWPORT_RE = re.compile(r"<meta[^>]+name=[\"']viewport[\"'][^>]*width\s*=\s*device-width", re.I)
YEAR_RE = re.compile(r"(?:©|&copy;|\(c\)|copyright)[^<]{0,60}?(20\d{2})(?:\s*[-–—]\s*(20\d{2}))?", re.I)
YEAR_AFTER_RE = re.compile(r"(20\d{2})(?:\s*[-–—]\s*(20\d{2}))?\s*(?:г\.?|год[а]?)?\s*(?:©|&copy;)", re.I)
HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"'#][^\"']*)[\"']", re.I)
CONTACT_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _text_of(page_html: str) -> str:
    cleaned = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page_html, flags=re.I | re.S)
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", cleaned))


def _decode(response: httpx.Response) -> str:
    if "charset" not in response.headers.get("content-type", "").lower():
        found = re.search(rb"charset=[\"']?([\w\-]+)", response.content[:3000])
        if found:
            try:
                return response.content.decode(found.group(1).decode("ascii"), "replace")
            except LookupError:
                pass
    return response.text


INTERNAL_ERROR = "адрес ведёт во внутреннюю сеть, такие сайты не проверяются"


def is_public_host(host: str) -> bool:
    """Адрес сайта берётся из чужих карточек, поэтому в локальную сеть и на сам компьютер не ходим."""
    if os.environ.get("SBORSHIK_ALLOW_PRIVATE") == "1":  # только для тестов на локальных макетах
        return True
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
        except (OSError, ValueError):
            return True  # имя не разрешилось: запрос сам завершится ошибкой «сайт не отвечает»
    return all(a.is_global for a in addresses)


def _fetch(client: httpx.Client, url: str) -> tuple[httpx.Response | None, str]:
    """GET с ручным проходом по перенаправлениям: каждый адрес проверяется отдельно."""
    try:
        for _hop in range(6):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or not is_public_host(parsed.hostname):
                return None, INTERNAL_ERROR
            response = client.get(url)
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            return response, ""
        return None, "слишком много перенаправлений"
    except httpx.ConnectError as exc:
        cause = exc.__cause__ or exc
        if isinstance(cause, ssl.SSLError) or "SSL" in str(exc) or "certificate" in str(exc).lower():
            return None, "ssl"
        return None, "сайт не отвечает"
    except httpx.TimeoutException:
        return None, "сайт не ответил за отведённое время"
    except httpx.HTTPError as exc:
        return None, f"ошибка соединения: {type(exc).__name__}"


def _footer_year(page_html: str) -> int:
    this_year = dt.date.today().year
    years: list[int] = []
    for regex in (YEAR_RE, YEAR_AFTER_RE):
        for match in regex.finditer(page_html):
            years += [int(y) for y in match.groups() if y]
    if not years:
        footer = re.search(r"<footer\b.*?</footer>", page_html, re.I | re.S)
        if footer:
            years = [int(y) for y in re.findall(r"\b(20\d{2})\b", _text_of(footer.group(0)))]
    years = [y for y in years if 2000 <= y <= this_year + 1]
    return max(years) if years else 0


def extract_contacts(page_html: str, base_url: str) -> dict:
    found: dict = {"phones": [], "emails": []}
    for href in HREF_RE.findall(page_html):
        href = html_lib.unescape(href.strip())
        if href.startswith("//"):
            href = "https:" + href
        kind, value = textutil.classify_link(href)
        if kind == "phone" and value not in found["phones"]:
            found["phones"].append(value)
        elif kind == "email" and value not in found["emails"]:
            found["emails"].append(value)
        elif kind in ("telegram", "whatsapp", "max", "vk", "instagram", "booking"):
            found.setdefault(kind, value)
    text = _text_of(page_html)
    for phone in textutil.find_phones(text):
        if phone not in found["phones"]:
            found["phones"].append(phone)
    for email in textutil.find_emails(text):
        if email not in found["emails"]:
            found["emails"].append(email)
    found["phones"] = found["phones"][:6]
    found["emails"] = found["emails"][:5]
    return found


def _contact_pages(page_html: str, base_url: str) -> list[str]:
    host = textutil.domain_of(base_url)
    pages: list[str] = []
    for href, label in CONTACT_LINK_RE.findall(page_html):
        mark = (href + " " + re.sub(r"<[^>]+>", "", label)).lower()
        if not re.search(r"контакт|contact|kontakt|о компании|about", mark):
            continue
        url = urljoin(base_url, html_lib.unescape(href))
        if textutil.domain_of(url) == host and url.startswith("http") and url not in pages and url.rstrip("/") != base_url.rstrip("/"):
            pages.append(url)
    return pages[:2]


def check(site: str, timeout: int = 20) -> dict:
    """Возвращает признаки сайта и найденные на нём контакты."""
    result: dict = {
        "site_status": "down", "site_error": "", "site_ssl": 0, "site_calc": 0, "site_form": 0, "site_booking": 0,
        "site_chat": 0, "site_mobile": 0, "site_year": 0, "site_checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "phones": [], "emails": [], "title": "",
    }
    host = textutil.domain_of(site)
    if not host:
        result["site_error"] = "некорректный адрес сайта"
        return result
    port = urlparse(site if "://" in site else "http://" + site).port
    netloc = f"{host}:{port}" if port else host
    timeout = min(int(timeout), 25)
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"}) as client:
        response, error = (None, "")
        if not site.startswith("http://"):
            response, error = _fetch(client, f"https://{netloc}/")
        if response is not None and response.url.scheme == "https":
            result["site_ssl"] = 1
        if response is None:
            first_error = "нет SSL-сертификата или он недействителен" if error == "ssl" else error
            response, error = _fetch(client, f"http://{netloc}/")
            if response is None:
                result["site_error"] = first_error or error
                return result
            result["site_ssl"] = 1 if response.url.scheme == "https" else 0
        if response.status_code in (401, 403, 429):
            result.update(site_status="unknown", site_error=f"сайт не пустил проверку (код {response.status_code})")
            return result
        if response.status_code >= 400:
            result["site_error"] = f"сайт отвечает ошибкой {response.status_code}"
            return result
        page_html = _decode(response)
        base_url = str(response.url)
        result["site_status"] = "ok"
        title = TITLE_RE.search(page_html)
        result["title"] = re.sub(r"\s+", " ", html_lib.unescape(title.group(1))).strip() if title else ""
        result["site_calc"] = 1 if CALC_RE.search(page_html) else 0
        has_form = any(FORM_FIELD_RE.search(form) for form in FORM_RE.findall(page_html))
        result["site_form"] = 1 if has_form or FORM_TEXT_RE.search(page_html) else 0
        result["site_chat"] = 1 if CHAT_RE.search(page_html) else 0
        result["site_mobile"] = 1 if VIEWPORT_RE.search(page_html) else 0
        result["site_year"] = _footer_year(page_html)
        contacts = extract_contacts(page_html, base_url)
        for url in _contact_pages(page_html, base_url):
            extra, _ = _fetch(client, url)
            if extra is not None and extra.status_code < 400:
                more = extract_contacts(_decode(extra), url)
                for key, value in more.items():
                    if isinstance(value, list):
                        contacts[key] = list(dict.fromkeys(contacts.get(key, []) + value))
                    else:
                        contacts.setdefault(key, value)
        result["site_booking"] = 1 if contacts.get("booking") or BOOKING_TEXT_RE.search(page_html) or any(
            dom in page_html for dom in textutil.BOOKING_SERVICES) else 0
        if result["site_booking"] and not contacts.get("booking"):
            service = next((name for dom, name in textutil.BOOKING_SERVICES.items() if dom in page_html), "на сайте")
            contacts["booking"] = service
        result.update(contacts)
    return result
