#!/usr/bin/env python3
"""Node agent: keeps the local Xray config in sync with the panel and reports per-user traffic.

Pure standard library so it runs on any stock Ubuntu/Debian. Configured by environment:
  PANEL_URL   https://panel.example.com
  NODE_TOKEN  token shown on the node's page in the admin panel
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PANEL_URL = os.environ["PANEL_URL"].rstrip("/")
NODE_TOKEN = os.environ["NODE_TOKEN"]
XRAY_BIN = os.getenv("XRAY_BIN", "/usr/local/bin/xray")
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
INTERVAL = int(os.getenv("SYNC_INTERVAL", "30"))
API = "127.0.0.1:10085"


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def request(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        PANEL_URL + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {NODE_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def current_hash() -> str:
    try:
        with open(XRAY_CONFIG, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return ""


def apply_config(config: dict) -> None:
    raw = json.dumps(config, indent=2, ensure_ascii=False).encode()
    if hashlib.sha256(raw).hexdigest() == current_hash():
        return
    tmp = XRAY_CONFIG + ".new"
    with open(tmp, "wb") as f:
        f.write(raw)
    check = subprocess.run([XRAY_BIN, "run", "-test", "-c", tmp], capture_output=True, text=True)
    if check.returncode != 0:
        log("panel sent an invalid config, keeping the old one:", check.stdout[-500:], check.stderr[-500:])
        os.remove(tmp)
        return
    os.replace(tmp, XRAY_CONFIG)
    subprocess.run(["systemctl", "restart", "xray"], check=False)
    log("config updated, xray restarted")


def collect_stats() -> dict:
    """Read and reset per-user counters: {"u12": {"up": 1, "down": 2}}."""
    out = subprocess.run(
        [XRAY_BIN, "api", "statsquery", f"--server={API}", "-pattern", "user>>>", "-reset"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    users: dict[str, dict[str, int]] = {}
    for item in json.loads(out.stdout).get("stat", []):
        # name looks like "user>>>u12>>>traffic>>>uplink"
        parts = item.get("name", "").split(">>>")
        value = int(item.get("value", 0) or 0)
        if len(parts) != 4 or not value:
            continue
        key = "up" if parts[3] == "uplink" else "down"
        users.setdefault(parts[1], {"up": 0, "down": 0})[key] += value
    return users


def main():
    log("agent started, panel:", PANEL_URL)
    pending: dict[str, dict[str, int]] = {}
    while True:
        try:
            apply_config(request("GET", "/api/node/config"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            log("config sync failed:", e)

        # Counters are reset as soon as they are read, so keep them until the panel accepts them.
        try:
            for email, v in collect_stats().items():
                acc = pending.setdefault(email, {"up": 0, "down": 0})
                acc["up"] += v["up"]
                acc["down"] += v["down"]
        except (OSError, ValueError) as e:
            log("stats read failed:", e)
        if pending:
            try:
                request("POST", "/api/node/stats", {"users": pending})
                pending = {}
            except (urllib.error.URLError, OSError, ValueError) as e:
                log("stats upload failed, will retry:", e)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
