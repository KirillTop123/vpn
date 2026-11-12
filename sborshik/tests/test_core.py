import datetime as dt

import textutil


def test_phones_and_links():
    assert textutil.norm_phone("8 (843) 123-45-67") == "78431234567"
    assert textutil.find_phones("Звоните: +7 917 222 33 44, 8(843)2000000, заказ 123456") == ["79172223344", "78432000000"]
    assert textutil.find_emails("info@potolki-kzn.ru, logo@2x.png") == ["info@potolki-kzn.ru"]
    assert textutil.classify_link("https://t.me/potolki_kzn") == ("telegram", "https://t.me/potolki_kzn")
    assert textutil.classify_link("https://api.whatsapp.com/send?phone=79172223344") == ("whatsapp", "https://wa.me/79172223344")
    assert textutil.classify_link("https://n12345.yclients.com/") == ("booking", "YClients")
    assert textutil.classify_link("http://www.potolki-kzn.ru/contacts") == ("site", "http://potolki-kzn.ru")
    assert textutil.classify_link("https://vk.com/share.php?url=x") == ("", "")
    assert textutil.classify_link("https://max.ru/potolki") == ("max", "https://max.ru/potolki")


def test_unwrap_2gis_link():
    import base64
    packed = base64.urlsafe_b64encode("https://potolki-kzn.ru/\nhttps://s1.bss.2gis.com/x".encode()).decode().rstrip("=")
    assert textutil.classify_link(f"https://link.2gis.ru/1.2/AAAA/webapi/20260101/{packed}") == ("site", "https://potolki-kzn.ru")


def test_dedupe_and_segments(fresh_db):
    db = fresh_db
    a, created = db.upsert_company({"name": "Потолки Казани", "address": "ул. Баумана, 5", "phones": ["+7 843 200-00-00"],
                                    "city": "Казань", "reviews": 80, "rating": 4.8, "card_urls": {"2gis": "u1"}})
    assert created
    b, created = db.upsert_company({"name": "ПОТОЛКИ КАЗАНИ, студия", "phones": ["8(843)2000000", "+79172223344"],
                                    "site": "potolki-kzn.ru", "telegram": "https://t.me/pk", "card_urls": {"yandex_maps": "u2"}})
    assert (b, created) == (a, False)                      # склейка по телефону
    c, created = db.upsert_company({"name": "Другое имя", "site": "https://www.potolki-kzn.ru/"})
    assert (c, created) == (a, False)                      # склейка по сайту
    d, created = db.upsert_company({"name": "Потолки Казани", "address": "улица Баумана 5"})
    assert (d, created) == (a, False)                      # склейка по названию+адресу
    company = db.get_company(a)
    assert company["phones"] == ["78432000000", "79172223344"]
    assert set(company["card_urls"]) == {"2gis", "yandex_maps"}
    assert company["segment"] == "нет онлайн-записи" and "много отзывов" in company["tags"]

    e, _ = db.upsert_company({"name": "Автостекло — официальный дилер", "phones": ["+79000000001"]})
    assert db.get_company(e)["not_my_client"] == 1
    f, _ = db.upsert_company({"name": "Детейлинг Блеск", "phones": ["+79000000002"], "site": "blesk.ru"})
    db.update_company(f, {"site_status": "down"})
    assert db.get_company(f)["segment"] == "сайт не открывается"

    assert db.list_companies({"q": "блеск"})["total"] == 1
    assert db.list_companies({"hide_nmc": 1})["total"] == 2
    assert db.list_companies({"has_tg": 1})["items"][0]["id"] == a
    assert db.list_companies({"site_down": 1, "tag": "нет мессенджеров"})["total"] == 1


def test_status_and_today(fresh_db):
    db = fresh_db
    cid, _ = db.upsert_company({"name": "Студия", "phones": ["+79000000003"]})
    db.set_status(cid, "written")
    db.set_status(cid, "read")
    assert [h["status"] for h in db.company_history(cid)] == ["read", "written", "new"]
    old = (dt.datetime.now() - dt.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE companies SET status_changed_at = ? WHERE id = ?", (old, cid))
    assert [c["id"] for c in db.today()["read_silent"]] == [cid]
    assert db.backup().exists()


def test_export_import_roundtrip(fresh_db):
    import json
    import exporter
    db = fresh_db
    cid, _ = db.upsert_company({"name": "Студия Лоск", "phones": ["+79000000010"], "telegram": "https://t.me/losk", "reviews": 70})
    other, _ = db.upsert_company({"name": "Без телеграма", "phones": ["+79000000011"]})
    for fmt in ("xlsx", "csv", "json"):
        result = exporter.export(fmt, ["name", "phones", "segment"], {"has_tg": 1})
        assert result["count"] == 1 and open(result["path"], "rb").read()
    claude = json.load(open(exporter.export_for_claude({})["path"], encoding="utf-8"))
    assert {c["id"] for c in claude["компании"]} == {cid, other} and claude["компании"][0]["segment_reason"]
    answer = json.dumps([{"id": cid, "message": "Здравствуйте!"}, {"id": 999, "message": "нет такой"}], ensure_ascii=False)
    assert exporter.import_file("answer.json", answer.encode()) == {"updated": 1, "skipped": 1}
    assert db.get_company(cid)["message"] == "Здравствуйте!"
    csv_text = "ID;Статус;Заметки\n%d;Написал;из таблицы\n" % other
    assert exporter.import_file("x.csv", csv_text.encode("utf-8-sig"))["updated"] == 1
    assert (db.get_company(other)["status"], db.get_company(other)["notes"]) == ("written", "из таблицы")


def test_site_check_refuses_internal_addresses(monkeypatch):
    from enrich import site_check
    monkeypatch.delenv("SBORSHIK_ALLOW_PRIVATE")
    for address in ("http://127.0.0.1:8765", "http://192.168.1.1", "http://169.254.169.254", "http://localhost"):
        result = site_check.check(address)
        assert result["site_status"] == "down" and result["site_error"] == site_check.INTERNAL_ERROR, address
    assert site_check.is_public_host("93.184.216.34")


def test_settings_are_validated(fresh_db):
    import pytest
    with pytest.raises(ValueError):
        fresh_db.save_settings({"many_reviews": '"><img src=x onerror=alert(1)>'})
    with pytest.raises(ValueError):
        fresh_db.save_settings({"browser": "firefox<script>"})
    assert fresh_db.save_settings({"many_reviews": "70", "delay_min": 4})["many_reviews"] == 70
