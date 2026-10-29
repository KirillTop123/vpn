"""Client share links and the subscription body that Happ (and v2rayNG, Hiddify, Streisand…) import."""
import base64
from datetime import timezone
from urllib.parse import quote, urlencode

from .config import settings
from .models import Node, User


def _vless(uuid: str, node: Node, port: int, params: dict, title: str) -> str:
    base = {
        "encryption": "none",
        "security": "reality",
        "sni": node.sni,
        "fp": "chrome",
        "pbk": node.public_key,
        "sid": node.short_id,
    }
    base.update(params)
    host = f"[{node.address}]" if ":" in node.address else node.address
    return f"vless://{uuid}@{host}:{port}?{urlencode(base, quote_via=quote)}#{quote(title)}"


def node_links(user: User, node: Node) -> list[str]:
    title = f"{node.flag} {node.name}".strip()
    links = [_vless(user.uuid, node, node.port, {"type": "tcp", "flow": "xtls-rprx-vision"}, title)]
    if node.xhttp_port:
        xhttp = {"type": "xhttp", "path": node.xhttp_path, "mode": "auto"}
        links.append(_vless(user.uuid, node, node.xhttp_port, xhttp, f"{title} · XHTTP"))
    return links


def placeholder_link(title: str) -> str:
    """A non-working entry whose only purpose is to show a message in the server list."""
    return f"vless://00000000-0000-0000-0000-000000000000@0.0.0.0:1?encryption=none&type=tcp#{quote(title)}"


def subscription_lines(user: User, nodes: list[Node]) -> list[str]:
    if not user.is_active():
        if not user.enabled:
            reason = "⛔ Подписка отключена"
        elif user.traffic_limit and user.used_total >= user.traffic_limit:
            reason = "⛔ Трафик закончился — продлите в боте"
        else:
            reason = "⛔ Подписка истекла — продлите в боте"
        return [placeholder_link(reason)]
    lines: list[str] = []
    for node in nodes:
        lines.extend(node_links(user, node))
    return lines or [placeholder_link("⏳ Серверы обновляются, попробуйте позже")]


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def subscription_headers(user: User) -> dict[str, str]:
    """Headers understood by Happ: title, traffic/expiry bar, refresh interval, support button, announce."""
    # expires_at is stored as naive UTC; mark it so .timestamp() doesn't assume local time.
    expire = int(user.expires_at.replace(tzinfo=timezone.utc).timestamp()) if user.expires_at else 0
    headers = {
        "profile-title": "base64:" + _b64(settings.brand_name),
        "profile-update-interval": str(settings.update_interval_hours),
        "subscription-userinfo": (
            f"upload={user.used_up}; download={user.used_down}; total={user.traffic_limit}; expire={expire}"
        ),
        "profile-web-page-url": f"{settings.panel_url}/sub/{user.sub_token}",
    }
    if settings.support_url:
        headers["support-url"] = settings.support_url
    if settings.announce:
        headers["announce"] = "base64:" + _b64(settings.announce)
    return headers
