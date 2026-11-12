"""Проверка сайта компании: открывается ли, SSL, формы, запись, чат, контакты."""
from __future__ import annotations

import datetime as dt
import html as html_lib
import ipaddress
import os
import re
import socket
import ssl
import time
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
DNS_ERROR = "домен сайта не найден"


def _addresses(host: str) -> list[str]:
    """IP-адреса хоста (сначала IPv4). Пустой список, если имя не разрешилось."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        found = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)))
    except (OSError, ValueError):
        return []
    return sorted(found, key=lambda a: ":" in a)


def _is_allowed(address: str) -> bool:
    if os.environ.get("SBORSHIK_ALLOW_PRIVATE") == "1":  # только для тестов на локальных макетах
        return True
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def resolve_public(host: str) -> tuple[str, str]:
    """Разрешает имя один раз и возвращает (адрес для подключения, ошибка).
    Адрес сайта берётся из чужих карточек, поэтому в локальную сеть и на сам компьютер не ходим;
    если имя не разрешилось или хотя бы один адрес внутренний — отказ."""
    addresses = _addresses(host)
    if not addresses:
        return "", DNS_ERROR
    if not all(_is_allowed(a) for a in addresses):
        return "", INTERNAL_ERROR
    return addresses[0], ""


def _fetch(client: httpx.Client, url: str) -> tuple[httpx.Response | None, str]:
    """GET с ручным проходом по перенаправлениям. На каждом шаге имя разрешается один раз,
    проверяется, и подключение идёт именно к проверенному адресу (имя уходит в Host и SNI),
    поэтому подменить адрес между проверкой и запросом нельзя."""
    try:
        for _hop in range(6):
            parsed = urlparse(url)
            host = parsed.hostname
            if parsed.scheme not in ("http", "https") or not host:
                return None, INTERNAL_ERROR
            address, error = resolve_public(host)
            if error:
                return None, error
            literal = f"[{address}]" if ":" in address else address
            port = f":{parsed.port}" if parsed.port else ""
            pinned = parsed._replace(netloc=literal + port).geturl()
            response = client.get(pinned, headers={"Host": host + port}, extensions={"sni_hostname": host})
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            response.logical_url = url  # адрес с именем сайта, а не с IP
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
    """Последний год рядом со знаком ©: «© 2007—2026» → 2026. Только для справки, выводов по нему не делаем."""
    this_year = dt.date.today().year
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", page_html)).replace("\u00a0", " ")
    years: list[int] = []
    for match in re.finditer(r"©|\(c\)|copyright", text, re.I):
        around = text[max(0, match.start() - 25):match.end() + 60]
        years += [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", around)]
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


STYLE_LINK_RE = re.compile(r"<link\b[^>]*rel\s*=\s*[\"']?stylesheet[^>]*>", re.I)
INLINE_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
BUILDERS = {"tilda": "Tilda", "wix.com": "Wix", "wixstatic": "Wix", "webflow": "Webflow", "readymag": "Readymag",
            "flexbe": "Flexbe", "lpmotor": "LPmotor", "craftum": "Craftum", "taplink": "Taplink", "nethouse": "Nethouse",
            "ukit": "uKit", "insales": "InSales", "wp-content": "WordPress", "bitrix": "1С-Битрикс", "joomla": "Joomla"}
FREE_HOSTS = ("tilda.ws", "wixsite.com", "ucoz.ru", "ucoz.net", "narod.ru", "nethouse.ru", "ukit.me", "tb.ru", "taplink.cc",
              "github.io", "blogspot.com", "jimdo.com", "wordpress.com", "turbo.site", "clients.site")
FREE_MAIL = ("mail.ru", "gmail.com", "yandex.ru", "ya.ru", "bk.ru", "list.ru", "inbox.ru", "rambler.ru", "icloud.com")
MOTION_LIBS_RE = re.compile(r"swiper|slick|owl\.carousel|aos\.|wow\.js|gsap|fancybox|lottie|animate\.css|splide", re.I)
APP_RE = re.compile(r"__NEXT_DATA__|data-reactroot|id=[\"']__nuxt|ng-version|id=[\"']app[\"']|id=[\"']root[\"']", re.I)


def _internal_pages(page_html: str, base_url: str) -> int:
    """Сколько разных внутренних страниц видно в ссылках (без якорей и файлов)."""
    host = textutil.domain_of(base_url)
    paths = set()
    for href in HREF_RE.findall(page_html):
        url = urljoin(base_url, html_lib.unescape(href.strip()))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or textutil.domain_of(url) != host:
            continue
        path = parsed.path.rstrip("/").lower()
        if not path or re.search(r"\.(css|js|png|jpe?g|gif|svg|webp|ico|pdf|docx?|xlsx?|zip|xml|woff2?)$", path):
            continue
        paths.add(path)
    return len(paths)


def analyze_look(page_html: str, css: str, base_url: str) -> dict:
    """Оценивает, как сайт сделан: современный, простой (голый текст без оформления) или устаревший.
    Смотрит на вёрстку и стили, а не на год в подвале."""
    low = page_html.lower()
    styles = (css + " " + " ".join(INLINE_STYLE_RE.findall(page_html))).lower()
    builder = next((name for mark, name in BUILDERS.items() if mark in low), "")
    old = []
    if re.search(r"<font\b|<center\b|<marquee\b|\bbgcolor\s*=|<frameset\b|\.swf\b", low):
        old.append("оформление тегами 2000-х годов")
    layout_modern = bool(re.search(r"display\s*:\s*(inline-)?(flex|grid)", styles)) or bool(builder)
    if low.count("<table") >= 3 and not layout_modern:
        old.append("вёрстка таблицами")
    if re.search(r"<!doctype[^>]*(html 4|xhtml 1\.0 transitional)", low):
        old.append("устаревший стандарт разметки")
    if re.search(r"jquery[-./]1\.\d", low):
        old.append("библиотеки десятилетней давности")
    images = len(re.findall(r"<img\b|<picture\b|background(-image)?\s*:\s*url", low + styles))
    motion = bool(re.search(r"transition\s*:|animation(-name)?\s*:|@keyframes|transform\s*:", styles)) or bool(MOTION_LIBS_RE.search(low))
    fonts = bool(re.search(r"@font-face|fonts\.googleapis|fonts\.gstatic|typekit|font-display", low + styles))
    adaptive = bool(VIEWPORT_RE.search(page_html)) or "@media" in styles or bool(builder)
    words = len(_text_of(page_html).split())
    pages = _internal_pages(page_html, base_url)
    plain = []
    if not motion:
        plain.append("нет анимаций и эффектов")
    if not fonts:
        plain.append("стандартные шрифты")
    if images < 4:
        plain.append("почти нет фотографий")
    if not layout_modern:
        plain.append("простая вёрстка в одну колонку")
    if not adaptive:
        plain.append("не подстраивается под телефон")
    app_shell = bool(APP_RE.search(page_html)) and words < 80  # сайт рисуется скриптами: по HTML судить нельзя
    if app_shell:
        look, why = "", []
    elif len(old) >= 2 or (old and len(plain) >= 2):
        look, why = "устаревший", old + plain[:2]
    elif len(plain) >= 3 and not builder:
        look, why = "простой", plain
    else:
        look, why = "современный", []
    return {"look": look, "why": why, "pages": pages, "builder": builder, "words": words, "images": images, "adaptive": adaptive}


def find_issues(page_html: str, result: dict, contacts: dict, base_url: str, look: dict) -> list[list[str]]:
    """Всё, что на сайте мешает получать заявки. Возвращает пары [метка, пояснение]."""
    low = page_html.lower()
    text = _text_of(page_html)
    host = textutil.domain_of(base_url)
    issues: list[list[str]] = []

    def add(tag: str, why: str) -> None:
        issues.append([tag, why])

    if look["look"] == "устаревший":
        add("сайт устарел", "Сайт выглядит устаревшим: " + ", ".join(look["why"]))
    elif look["look"] == "простой":
        add("простой сайт", "Сайт слишком простой: " + ", ".join(look["why"]))
    if look["look"] and look["pages"] <= 1:
        add("одностраничный сайт", "Сайт из одной страницы: нет разделов с услугами, ценами и работами")
    if look["look"] and look["words"] < 120:
        add("мало текста", "На главной почти нет текста: непонятно, чем занимается компания, и поиск её не находит")
    if result["site_time"] >= 3:
        add("сайт медленный", f"Сайт открывается {result['site_time']:.1f} сек: половина посетителей столько не ждёт")
    if not result["site_calc"]:
        add("нет калькулятора", "Нет калькулятора: клиент не может сам прикинуть цену")
    if not re.search(r"₽|руб\.?|\bцен[аыу]\b|прайс|стоимость", text, re.I):
        add("нет цен", "На сайте нет цен: клиент уходит сравнивать к тем, у кого они есть")
    if contacts.get("phones") and "tel:" not in low:
        add("телефон не кликается", "Телефон на сайте нельзя нажать с мобильного: его приходится набирать вручную")
    if not contacts.get("phones"):
        add("нет телефона на сайте", "На главной странице сайта нет телефона")
    if not any(contacts.get(k) for k in ("telegram", "whatsapp", "max")):
        add("нет мессенджеров на сайте", "На сайте нет кнопок Telegram и WhatsApp: написать нельзя, только звонить")
    if not result["site_chat"] and not result["site_form"]:
        add("нет обратной связи", "На сайте нет ни формы, ни чата: оставить заявку негде")
    if not re.search(r"mc\.yandex\.ru|metrika|googletagmanager|google-analytics|gtag\(|top\.mail\.ru|liveinternet", low):
        add("нет счётчика", "Нет Метрики и аналитики: владелец не видит, сколько людей приходит и откуда")
    if result["site_form"] and not re.search(r"политик[аи] конфиденциальности|персональных данных|privacy", low):
        add("форма без политики", "Форма собирает телефоны без политики конфиденциальности: это штраф по 152-ФЗ")
    if not re.search(r"отзыв", text, re.I):
        add("нет отзывов на сайте", "На сайте нет отзывов клиентов")
    if not re.search(r"портфолио|наши работы|примеры работ|галере|выполненные|до и после|кейс", text, re.I) and look["images"] < 8:
        add("нет примеров работ", "На сайте нет примеров работ и фотографий результата")
    title = result.get("title", "")
    if len(title) < 10 or title.lower() in ("главная", "home", "index"):
        add("нет заголовка страницы", "У страницы нет нормального заголовка: в поиске сайт выглядит безымянным")
    if not re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'][^\"']{20,}", page_html, re.I):
        add("нет описания для поиска", "Нет описания для поисковиков: Яндекс показывает случайный кусок текста")
    if not re.search(r"<h1\b", low):
        add("нет главного заголовка", "На странице нет главного заголовка (h1): поисковикам сложнее понять тему")
    if not re.search(r"property=[\"']og:(image|title)", low):
        add("нет превью ссылки", "Ссылка на сайт в мессенджерах приходит без картинки и описания")
    if not re.search(r"rel=[\"'][^\"']*icon", low):
        add("нет значка сайта", "У сайта нет значка во вкладке браузера")
    if base_url.startswith("https://") and re.search(r"(src|href)=[\"']http://[^\"']+\.(js|css|png|jpe?g|gif|webp)", low):
        add("небезопасное содержимое", "Часть картинок и скриптов грузится по незащищённому адресу: браузер может их блокировать")
    free = next((dom for dom in FREE_HOSTS if host.endswith("." + dom)), "")
    if free:
        add("бесплатный домен", f"Сайт на бесплатном адресе конструктора ({host}): выглядит несолидно")
    if any(e.split("@")[-1] in FREE_MAIL for e in contacts.get("emails", [])) and not any(e.endswith("@" + host) for e in contacts.get("emails", [])):
        add("почта на бесплатном домене", "Почта на mail.ru/gmail, а не на домене компании")
    return issues


def check(site: str, timeout: int = 20) -> dict:
    """Возвращает признаки сайта, найденные на нём контакты и список проблем."""
    result: dict = {
        "site_status": "down", "site_error": "", "site_ssl": 0, "site_calc": 0, "site_form": 0, "site_booking": 0,
        "site_chat": 0, "site_mobile": 0, "site_year": 0, "site_time": 0.0, "site_look": "", "site_pages": 0,
        "site_issues": [], "site_checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
        started = time.monotonic()
        if not site.startswith("http://"):
            response, error = _fetch(client, f"https://{netloc}/")
        if response is None:
            first_error = "нет SSL-сертификата или он недействителен" if error == "ssl" else error
            if error in (INTERNAL_ERROR, DNS_ERROR):
                result["site_error"] = error
                return result
            started = time.monotonic()
            response, error = _fetch(client, f"http://{netloc}/")
            if response is None:
                result["site_error"] = first_error or error
                return result
        result["site_time"] = round(time.monotonic() - started, 1)
        result["site_ssl"] = 1 if response.logical_url.startswith("https://") else 0
        if response.status_code in (401, 403, 429):
            result.update(site_status="unknown", site_error=f"сайт не пустил проверку (код {response.status_code})")
            return result
        if response.status_code >= 400:
            result["site_error"] = f"сайт отвечает ошибкой {response.status_code}"
            return result
        page_html = _decode(response)
        base_url = response.logical_url
        result["site_status"] = "ok"
        title = TITLE_RE.search(page_html)
        result["title"] = re.sub(r"\s+", " ", html_lib.unescape(title.group(1))).strip() if title else ""
        result["site_calc"] = 1 if CALC_RE.search(page_html) else 0
        has_form = any(FORM_FIELD_RE.search(form) for form in FORM_RE.findall(page_html))
        result["site_form"] = 1 if has_form or FORM_TEXT_RE.search(page_html) else 0
        result["site_chat"] = 1 if CHAT_RE.search(page_html) else 0
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
        css = ""
        for tag in STYLE_LINK_RE.findall(page_html)[:4]:  # стили нужны, чтобы оценить оформление
            href = HREF_RE.search(tag)
            if not href:
                continue
            sheet, _ = _fetch(client, urljoin(base_url, html_lib.unescape(href.group(1))))
            if sheet is not None and sheet.status_code < 400:
                css += sheet.text[:400_000] + "\n"
        look = analyze_look(page_html, css, base_url)
        result["site_look"], result["site_pages"] = look["look"], look["pages"]
        result["site_mobile"] = 1 if look["adaptive"] else 0
        result["site_booking"] = 1 if contacts.get("booking") or BOOKING_TEXT_RE.search(page_html) or any(
            dom in page_html for dom in textutil.BOOKING_SERVICES) else 0
        if result["site_booking"] and not contacts.get("booking"):
            service = next((name for dom, name in textutil.BOOKING_SERVICES.items() if dom in page_html), "на сайте")
            contacts["booking"] = service
        result["site_issues"] = find_issues(page_html, result, contacts, base_url, look)
        if result["site_ssl"] and not port:
            plain, _ = _fetch(client, f"http://{netloc}/")
            if plain is not None and plain.logical_url.startswith("http://") and plain.status_code < 400:
                result["site_issues"].append(["нет перехода на https", "Старый адрес http:// не переводит на защищённый: часть посетителей видит «Не защищено»"])
        result.update(contacts)
    return result
