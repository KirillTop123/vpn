"""Сквозная проверка сбора на локальных макетах сайтов (настоящие сайты не трогаем)."""
import json
import os
import time
from pathlib import Path

import pytest

import config
import fake_sites

CHROMIUM = "/opt/pw-browsers/chromium"


@pytest.fixture()
def env(fresh_db, monkeypatch):
    server = fake_sites.start()
    port = server.server_address[1]
    fake_sites.STATE.update(captcha_solved=False, hits=[])
    selectors = json.loads((config.resource_dir() / "data" / "selectors.json").read_text("utf-8"))
    selectors["twogis"]["base_url"] = f"http://127.0.0.1:{port}/2gis"
    selectors["yandex_maps"]["base_url"] = f"http://127.0.0.1:{port}/ya"
    selectors["yandex_search"]["base_url"] = f"http://127.0.0.1:{port}/ya"
    (config.user_dir() / "selectors.json").write_text(json.dumps(selectors, ensure_ascii=False), "utf-8")
    monkeypatch.setenv("SBORSHIK_HEADLESS", "1")
    if Path(CHROMIUM).exists() and "SBORSHIK_CHROMIUM" not in os.environ:
        found = next(Path(CHROMIUM).rglob("chrome"), None) if Path(CHROMIUM).is_dir() else Path(CHROMIUM)
        if found:
            monkeypatch.setenv("SBORSHIK_CHROMIUM", str(found))
    fresh_db.save_settings({"delay_min": 0.0, "delay_max": 0.05, "page_timeout": 5})
    import collector as collector_module
    yield fresh_db, collector_module.Collector(), port
    server.shutdown()
    (config.user_dir() / "selectors.json").unlink()


def wait_for(predicate, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_full_collection(env):
    db, col, port = env
    col.start({"city": "Казань", "niche": "натяжные потолки", "queries": ["натяжные потолки"],
               "sources": ["twogis", "yandex_maps", "yandex_search"], "enrich": True, "find_sites": True})
    assert wait_for(lambda: col.status == "captcha"), [entry["text"] for entry in col.snapshot()["logs"]]
    assert "Решите капчу" in col.snapshot()["message"]
    time.sleep(0.5)
    assert col.status == "captcha"                       # стоит и ждёт человека, сам ничего не делает
    fake_sites.STATE["captcha_solved"] = True
    col.resume()                                         # нажали «Продолжить»: страница ещё с капчей → переоткроет
    col.join(90)
    snap = col.snapshot()
    logs = "\n".join(entry["text"] for entry in snap["logs"])
    assert snap["job"]["status"] == "done", logs
    by_name = {c["name"]: c for c in db.list_companies()["items"]}
    assert set(by_name) == {"Потолки Казани", "Небо", "Потолок-Сервис", "Глянец", "Лофт Потолок", "Потолок Плюс"}, logs

    main = by_name["Потолки Казани"]                      # 2ГИС + Яндекс Карты + поиск склеены в одну
    assert set(main["card_urls"]) == {"2gis", "yandex_maps", "yandex_search"}
    assert main["phones"] == ["78432000001"] and main["district"] == "Вахитовский район"
    assert main["site"] == f"http://127.0.0.2:{port}" and main["telegram"] == "https://t.me/potolki_kzn"
    assert main["whatsapp"] == "https://wa.me/79172000001" and main["vk"] == "https://vk.com/potolki_kzn"
    assert "zakaz@potolki.example" in main["emails"] and "info@potolki.example" in main["emails"]
    assert (main["site_status"], main["site_form"], main["site_calc"], main["site_chat"], main["site_mobile"],
            main["site_year"], main["site_ssl"]) == ("ok", 1, 1, 1, 1, 2021, 0)
    assert main["reviews"] == 120 and main["hours"] == "Пн–Пт 09:00–19:00; Сб–Вс выходной"

    nebo = by_name["Небо"]                                # сайт найден через поиск по названию и городу
    assert nebo["site"] == f"http://127.0.0.3:{port}" and nebo["site_found_by"] == "search"
    assert nebo["telegram"] == "https://t.me/nebo_kzn" and nebo["vk"] == "" and nebo["rating"] == 4.6
    assert nebo["reviews"] == 12 and nebo["address"] == "проспект Победы, 100"

    assert by_name["Потолок-Сервис"]["not_my_client"] == 1
    assert by_name["Глянец"]["site_status"] == "down" and by_name["Глянец"]["segment"] == "сайт не открывается"
    loft = by_name["Лофт Потолок"]
    assert loft["booking"] == "YClients" and loft["whatsapp"] == "https://wa.me/79172000005"
    assert loft["phones"] == ["78432000005"] and loft["segment"] == "нет сайта"
    assert by_name["Потолок Плюс"]["emails"] == ["plus@potolok.example"]


def test_stop_and_resume(env):
    db, col, _port = env
    fake_sites.STATE["captcha_solved"] = True
    db.save_settings({"delay_min": 0.4, "delay_max": 0.5})
    job_id = col.start({"city": "Казань", "queries": ["натяжные потолки"], "sources": ["twogis"], "enrich": False})
    assert wait_for(lambda: db.query("SELECT COUNT(*) AS n FROM job_cards WHERE status = 'done'")[0]["n"] >= 1)
    col.pause()
    assert wait_for(lambda: col.status == "paused")
    done_at_pause = db.query("SELECT COUNT(*) AS n FROM job_cards WHERE status = 'done'")[0]["n"]
    time.sleep(1.2)
    assert db.query("SELECT COUNT(*) AS n FROM job_cards WHERE status = 'done'")[0]["n"] <= done_at_pause + 1
    col.stop()
    col.join(20)
    assert db.query("SELECT status FROM jobs WHERE id = ?", (job_id,))[0]["status"] == "paused"
    assert col.snapshot()["resumable"]

    import collector as collector_module
    again = collector_module.Collector()                 # «программу закрыли и открыли снова»
    again.resume_job(job_id)
    again.join(60)
    assert db.query("SELECT status FROM jobs WHERE id = ?", (job_id,))[0]["status"] == "done"
    assert db.list_companies()["total"] == 4
    firm_hits = [path for _host, path in fake_sites.STATE["hits"] if "/firm/" in path]
    assert len(firm_hits) == len(set(firm_hits)) == 4      # ни одна карточка не открывалась дважды
