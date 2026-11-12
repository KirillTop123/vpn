"""Локальные копии-макеты источников для проверки сбора без обращения к настоящим сайтам."""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

STATE = {"captcha_solved": False, "hits": []}


def wrap(url: str) -> str:
    packed = base64.urlsafe_b64encode(f"{url}\nhttps://s1.bss.2gis.com/x".encode()).decode().rstrip("=")
    return f"https://link.2gis.ru/1.2/ABCDEF/webapi/20260101/{packed}"


def page(body: str, head: str = "") -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'>{head}</head><body>{body}</body></html>"


def firm_page(firm_id: str, port: int) -> str:
    if firm_id == "1001":
        item = {
            "id": "1001_abcdef", "name": "Потолки Казани, студия натяжных потолков", "address_name": "улица Баумана, 5",
            "adm_div": [{"type": "city", "name": "Казань"}, {"type": "district", "name": "Вахитовский район"}],
            "rubrics": [{"name": "Натяжные потолки"}, {"name": "Световые линии"}],
            "reviews": {"general_rating": 4.9, "general_review_count": 120},
            "org": {"branch_count": 1},
            "schedule": {d: {"working_hours": [{"from": "09:00", "to": "19:00"}]} for d in ("Mon", "Tue", "Wed", "Thu", "Fri")},
            "contact_groups": [{"contacts": [
                {"type": "phone", "value": "+78432000001", "text": "+7 (843) 200‒00‒01"},
                {"type": "website", "value": wrap(f"http://127.0.0.2:{port}/"), "text": "potolki.example", "url": wrap(f"http://127.0.0.2:{port}/")},
                {"type": "telegram", "value": "https://t.me/potolki_kzn", "url": "https://t.me/potolki_kzn"},
                {"type": "email", "value": "Info@potolki.example"},
            ]}],
        }
        state = json.dumps({"data": {"entity": {"profile": {"1001": {"data": item}}}}}, ensure_ascii=False)
        return page(f"<h1>Потолки Казани</h1><script>var initialState = {state};</script>")
    if firm_id == "1002":
        return page("<h1>Небо</h1><a href='/kazan/geo/1'>проспект Победы, 100</a>"
                    "<a href='/kazan/search/x/rubricId/1'>Натяжные потолки</a>"
                    "<a href='tel:+78432000002'>+7 843 200-00-...</a><span data-field='rating'>4,6</span>"
                    "<a href='/kazan/firm/1002/tab/reviews'>Отзывы 12</a>"
                    "<a href='https://vk.com/2gis'>2ГИС ВКонтакте</a>")
    if firm_id == "1003":
        if not STATE["captcha_solved"]:
            return page("<div id='captcha'>Подтвердите, что вы не робот</div>")
        return page("<h1>Потолок-Сервис, официальный дилер</h1><a href='tel:+78432000003'>тел</a>")
    if firm_id == "1004":
        return page(f"<h1>Глянец</h1><a href='tel:88432000004'>тел</a>"
                    f"<a href='{wrap('http://127.0.0.9:1/')}'>glyanec.example</a>")
    return page("<p>Не найдено</p>")


def ymaps_card(org_id: str) -> str:
    if org_id == "5550001":
        return page("<div class='orgpage-view'><h1 class='orgpage-header-view__header'>Потолки Казани</h1>"
                    "<div class='orgpage-header-view__address'>ул. Баумана, 5</div>"
                    "<div class='orgpage-phones-view__phone-number'>+7 (843) 200-00-01</div>"
                    "<span class='business-rating-badge-view__rating-text'>4,8</span>"
                    "<div class='business-header-rating-view__text'>87 оценок</div></div>")
    if org_id == "5550002":
        return page("<div class='orgpage-view'><h1 class='orgpage-header-view__header'>Лофт Потолок</h1>"
                    "<div class='orgpage-header-view__address'>ул. Чистопольская, 20</div>"
                    "<a class='orgpage-categories-info-view__link'>Натяжные потолки</a>"
                    "<div class='card-phones-view__more'>Показать телефон</div>"
                    "<div class='orgpage-phones-view__phone-number'>8 (843) 200-00-05</div>"
                    "<div class='business-working-status-view'>Открыто до 20:00</div>"
                    "<a href='https://wa.me/79172000005'>WhatsApp</a><a href='https://n777.yclients.com/'>Записаться</a>"
                    "<span class='business-rating-badge-view__rating-text'>5,0</span>"
                    "<div class='business-header-rating-view__text'>7 оценок</div></div>")
    return page("<p>нет</p>")


YMAPS_LIST = page("""
<div class='scroll__container' style='height:200px;overflow:auto'><div id='list' style='min-height:600px'>
<a href='/maps/org/potolki_kazani/5550001/'>Потолки Казани</a></div></div>
<script>
const box = document.querySelector('.scroll__container'); let loaded = false;
box.addEventListener('scroll', () => { if (loaded) return; loaded = true;
  document.getElementById('list').insertAdjacentHTML('beforeend', "<a href='/maps/org/loft/5550002/'>Лофт</a><div class='add-business-view'>Добавить организацию</div>"); });
</script>""")


def serp(text: str, page_no: int, port: int) -> str:
    items = []
    if "небо" in text.lower():
        items = [(f"http://127.0.0.3:{port}/", "Небо — натяжные потолки в Казани", "Студия Небо. Монтаж за 1 день.")]
    elif "натяжные потолки" in text.lower() and page_no == 0:
        items = [
            ("https://zoon.ru/kazan/potolki/", "Натяжные потолки в Казани — Zoon", "каталог"),
            (f"http://127.0.0.2:{port}/", "Потолки Казани — официальный сайт", "Казань"),
            (f"http://127.0.0.4:{port}/", "Потолок Плюс | натяжные потолки Казань", "Казань, звоните"),
        ]
    body = "".join(f"<li class='serp-item'><h2><a class='OrganicTitle-Link' href='{u}'><span class='OrganicTitle-LinkText'>{t}</span></a></h2>"
                   f"<span class='OrganicTextContentSpan'>{s}</span></li>" for u, t, s in items)
    return page(f"<ul>{body}</ul>")


SITES = {
    "127.0.0.2": page(
        "<header><a href='/contacts'>Контакты</a></header><h1>Потолки Казани</h1>"
        "<form><input type='tel' name='phone'><button>Оставить заявку</button></form>"
        "<div class='calc'>Калькулятор стоимости</div><a href='https://wa.me/79172000001'>WhatsApp</a>"
        "<script src='//code.jivosite.com/widget/abc'></script><footer>© 2021 Потолки Казани</footer>",
        "<title>Потолки Казани — натяжные потолки</title><meta name='viewport' content='width=device-width, initial-scale=1'>"),
    "127.0.0.3": page("<h1>Небо</h1><p>Звоните: 8 (843) 200-00-02</p><a href='https://t.me/nebo_kzn'>Telegram</a>"
                      "<footer>&copy; 2019-2026 Небо</footer>", "<title>Небо</title>"),
    "127.0.0.4": page("<h1>Потолок Плюс</h1><a href='tel:+78432000006'>+7 843 200-00-06</a>"
                      "<a href='mailto:plus@potolok.example'>почта</a>", "<title>Потолок Плюс | Казань</title>"),
}
CONTACTS = page("<p>Почта: zakaz@potolki.example</p><a href='https://vk.com/potolki_kzn'>VK</a>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        host = self.headers.get("Host", "").split(":")[0]
        port = self.server.server_address[1]
        STATE["hits"].append((host, path))
        parts = [p for p in path.split("/") if p]
        body, code = "", 200
        if host in SITES:
            body = CONTACTS if path == "/contacts" and host == "127.0.0.2" else SITES[host]
        elif parts[:1] == ["2gis"]:
            if parts[-1] == "solve":  # «человек решил капчу» — для ручной проверки интерфейса
                STATE["captcha_solved"] = True
                body = "ok"
            elif "search" in parts:
                page_no = int(parts[-1])
                ids = {1: ["1001", "1002", "1003"], 2: ["1004", "1001"]}.get(page_no, [])
                body = page("".join(f"<a href='/2gis/kazan/firm/{i}'>Фирма {i}</a>" for i in ids))
            elif "firm" in parts:
                body = firm_page(parts[parts.index("firm") + 1], port)
        elif parts[:2] == ["ya", "maps"]:
            body = ymaps_card(parts[-1]) if "org" in parts else YMAPS_LIST
        elif parts[:2] == ["ya", "search"]:
            query = parse_qs(url.query)
            body = serp(query.get("text", [""])[0], int(query.get("p", ["0"])[0]), port)
        else:
            code, body = 404, page("404")
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
