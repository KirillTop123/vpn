import base64
import json
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkdtemp() + "/test.db"
os.environ["ADMIN_PASSWORD"] = "secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Node, Payment, User, utcnow  # noqa: E402
from app.services import apply_payment, get_or_create_tg_user, start_trial  # noqa: E402
from app.xray_config import build_config  # noqa: E402

init_db()


@pytest.fixture()
def db():
    s = SessionLocal()
    for model in (Payment, User, Node):
        s.query(model).delete()
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def client():
    return TestClient(app)


def make_node(db, **kw):
    kw = {"name": "NL", "flag": "🇳🇱", "address": "203.0.113.1", "sni": "www.microsoft.com", **kw}
    node = Node(**kw)
    db.add(node)
    db.commit()
    return node


def make_user(db, days=30, **kw):
    user = User(username="ivan", expires_at=utcnow(), **kw)
    user.extend(days)
    db.add(user)
    db.commit()
    return user


def decode_sub(resp) -> list[str]:
    return base64.b64decode(resp.text).decode().splitlines()


def test_subscription_flow(db, client):
    user = make_user(db)
    node = make_node(db)
    auth = {"Authorization": f"Bearer {node.token}"}

    # Node has never checked in -> not offered to clients.
    lines = decode_sub(client.get(f"/sub/{user.sub_token}", headers={"User-Agent": "Happ/1.0"}))
    assert len(lines) == 1 and "0.0.0.0" in lines[0]

    cfg = client.get("/api/node/config", headers=auth).json()
    ids = [c["id"] for c in cfg["inbounds"][1]["settings"]["clients"]]
    assert user.uuid in ids

    resp = client.get(f"/sub/{user.sub_token}", headers={"User-Agent": "Happ/1.0"})
    lines = decode_sub(resp)
    assert len(lines) == 2  # Vision + XHTTP
    vision = urlparse(lines[0])
    q = {k: v[0] for k, v in parse_qs(vision.query).items()}
    assert vision.scheme == "vless" and vision.username == user.uuid
    assert vision.hostname == "203.0.113.1" and vision.port == 443
    assert q["security"] == "reality" and q["pbk"] == node.public_key and q["sid"] == node.short_id
    assert q["flow"] == "xtls-rprx-vision" and q["sni"] == "www.microsoft.com"
    assert unquote(vision.fragment) == "🇳🇱 NL"
    xhttp = {k: v[0] for k, v in parse_qs(urlparse(lines[1]).query).items()}
    assert xhttp["type"] == "xhttp" and xhttp["path"] == node.xhttp_path

    assert base64.b64decode(resp.headers["profile-title"].removeprefix("base64:"))
    info = dict(p.strip().split("=") for p in resp.headers["subscription-userinfo"].split(";"))
    assert abs(int(info["expire"]) - (utcnow() + timedelta(days=30)).timestamp()) < 24 * 3600 + 60

    # Browser gets an HTML page with the Happ deep link.
    page = client.get(f"/sub/{user.sub_token}", headers={"Accept": "text/html"})
    assert "happ://add/" in page.text


def test_expired_and_traffic_limited_users_are_excluded(db, client):
    node = make_node(db, last_seen=utcnow())
    expired = make_user(db, days=-1)
    limited = make_user(db, traffic_limit=100, used_down=100)
    ok = make_user(db)

    cfg = client.get("/api/node/config", headers={"Authorization": f"Bearer {node.token}"}).json()
    ids = {c["id"] for c in cfg["inbounds"][1]["settings"]["clients"]}
    assert ids == {ok.uuid}

    lines = decode_sub(client.get(f"/sub/{expired.sub_token}"))
    assert len(lines) == 1 and "истекла" in unquote(lines[0])
    assert "Трафик" in unquote(decode_sub(client.get(f"/sub/{limited.sub_token}"))[0])


def test_traffic_stats(db, client):
    node = make_node(db)
    user = make_user(db)
    r = client.post(
        "/api/node/stats",
        json={"users": {user.email: {"up": 10, "down": 20}, "bridge5": {"up": 999, "down": 999}}},
        headers={"Authorization": f"Bearer {node.token}"},
    )
    assert r.status_code == 200
    db.refresh(user)
    assert (user.used_up, user.used_down) == (10, 20)
    assert client.post("/api/node/stats", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_bridge_config(db):
    exit_node = make_node(db, name="DE")
    bridge = make_node(db, name="Белые списки", address="198.51.100.7", sni="ya.ru", upstream_id=exit_node.id)
    db.refresh(bridge)
    user = make_user(db)

    bcfg = build_config(bridge, [user], [])
    up = bcfg["outbounds"][0]
    assert up["tag"] == "upstream"  # default route goes abroad
    assert up["settings"]["vnext"][0]["address"] == exit_node.address
    assert up["settings"]["vnext"][0]["users"][0]["id"] == bridge.bridge_uuid
    assert up["streamSettings"]["realitySettings"]["publicKey"] == exit_node.public_key
    assert any(r.get("outboundTag") == "direct" and "geoip:ru" in r.get("ip", []) for r in bcfg["routing"]["rules"])

    ecfg = build_config(exit_node, [user], [bridge])
    ids = [c["id"] for c in ecfg["inbounds"][1]["settings"]["clients"]]
    assert bridge.bridge_uuid in ids
    assert ecfg["outbounds"][0]["tag"] == "direct"


@pytest.mark.skipif(not shutil.which("xray"), reason="xray binary not installed")
def test_config_passes_xray_validation(db, tmp_path):
    exit_node = make_node(db)
    bridge = make_node(db, name="RU", upstream_id=exit_node.id)
    db.refresh(bridge)
    user = make_user(db)
    for node, bridges in ((exit_node, [bridge]), (bridge, [])):
        path = tmp_path / f"{node.id}.json"
        path.write_text(json.dumps(build_config(node, [user], bridges)))
        res = subprocess.run(["xray", "run", "-test", "-c", str(path)], capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr


def test_trial_payment_and_referral(db):
    referrer, _ = get_or_create_tg_user(db, 100, "ref")
    user, created = get_or_create_tg_user(db, 200, "new", str(referrer.id))
    assert created and user.referred_by == referrer.id and not user.is_active()

    assert start_trial(db, user) and user.is_active()
    assert not start_trial(db, user)

    before = user.expires_at
    got = apply_payment(db, user, 30, 150, "XTR", "charge-1")
    assert got.id == referrer.id
    assert user.expires_at - before == timedelta(days=30)
    db.refresh(referrer)
    assert referrer.is_active()

    # Duplicate delivery of the same charge is ignored.
    assert apply_payment(db, user, 30, 150, "XTR", "charge-1") is None
    db.refresh(user)
    assert user.expires_at - before == timedelta(days=30)


def test_admin_requires_login_and_creates_users_and_nodes(db, client):
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert "Неверный" in client.post("/admin/login", data={"password": "bad"}).text
    client.post("/admin/login", data={"password": "secret"})
    assert client.get("/admin").status_code == 200

    client.post("/admin/users", data={"username": "petya", "days": 7, "traffic_gb": 50})
    u = db.query(User).filter_by(username="petya").one()
    assert u.is_active() and u.traffic_limit == 50 * 1024**3

    r = client.post("/admin/nodes", data={"name": "FI", "address": "1.2.3.4", "sni": "www.google.com"})
    node = db.query(Node).filter_by(name="FI").one()
    assert r.status_code == 200 and node.token in r.text  # redirected to page with install command
    assert client.get("/admin/nodes").status_code == 200
    assert client.get("/admin/payments").status_code == 200
