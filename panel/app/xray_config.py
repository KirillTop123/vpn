"""Builds the full Xray server config a node agent downloads and runs."""
from .models import Node, User

API_PORT = 10085

# Traffic from a bridge node to these destinations leaves directly from Russia
# (fast, and Russian services that block foreign IPs keep working).
RU_DOMAINS = ["regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$"]


def _reality(node: Node) -> dict:
    return {
        "show": False,
        "dest": f"{node.sni}:443",
        "xver": 0,
        "serverNames": [node.sni],
        "privateKey": node.private_key,
        "shortIds": [node.short_id],
    }


def build_config(node: Node, users: list[User], bridges: list[Node]) -> dict:
    """
    users   - active users that may connect to this node
    bridges - bridge nodes that use this node as their upstream exit
    """
    vision_clients = [{"id": u.uuid, "email": u.email, "flow": "xtls-rprx-vision"} for u in users]
    vision_clients += [
        {"id": b.bridge_uuid, "email": f"bridge{b.id}", "flow": "xtls-rprx-vision"} for b in bridges
    ]

    sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}
    inbounds = [
        {
            "tag": "api",
            "listen": "127.0.0.1",
            "port": API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        },
        {
            "tag": "vless-vision",
            "listen": "0.0.0.0",
            "port": node.port,
            "protocol": "vless",
            "settings": {"clients": vision_clients, "decryption": "none"},
            "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": _reality(node)},
            "sniffing": sniffing,
        },
    ]
    if node.xhttp_port:
        inbounds.append(
            {
                "tag": "vless-xhttp",
                "listen": "0.0.0.0",
                "port": node.xhttp_port,
                "protocol": "vless",
                "settings": {"clients": [{"id": u.uuid, "email": u.email} for u in users], "decryption": "none"},
                "streamSettings": {
                    "network": "xhttp",
                    "xhttpSettings": {"path": node.xhttp_path, "mode": "auto"},
                    "security": "reality",
                    "realitySettings": _reality(node),
                },
                "sniffing": sniffing,
            }
        )

    outbounds = [
        {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
        {"tag": "block", "protocol": "blackhole"},
    ]
    rules = [
        {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"},
    ]

    up = node.upstream
    if up is not None:
        # First outbound is the default route: everything not matched below goes abroad.
        outbounds.insert(
            0,
            {
                "tag": "upstream",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": up.address,
                            "port": up.port,
                            "users": [{"id": node.bridge_uuid, "flow": "xtls-rprx-vision", "encryption": "none"}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": up.sni,
                        "fingerprint": "chrome",
                        "publicKey": up.public_key,
                        "shortId": up.short_id,
                    },
                },
            },
        )
        rules += [
            {"type": "field", "domain": RU_DOMAINS, "outboundTag": "direct"},
            {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
        ]

    return {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["StatsService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
            "system": {"statsInboundUplink": False, "statsInboundDownlink": False},
        },
        "dns": {"servers": ["1.1.1.1", "8.8.8.8"]},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }
