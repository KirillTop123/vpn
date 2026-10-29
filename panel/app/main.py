import base64
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import admin
from .config import settings
from .db import get_db, init_db
from .links import subscription_headers, subscription_lines
from .models import Node, User, utcnow
from .services import active_users, node_bridges, record_traffic, visible_nodes
from .xray_config import build_config

BASE = Path(__file__).resolve().parent
NODE_FILES = Path(os.getenv("NODE_FILES_DIR", BASE.parent.parent / "node"))
templates = Jinja2Templates(directory=BASE / "templates")

log = logging.getLogger("panel")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.admin_password == "admin" or settings.secret_key == "change-me":
        log.warning("ADMIN_PASSWORD / SECRET_KEY are defaults — set them in .env before going public!")
    yield


app = FastAPI(title=settings.brand_name, docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=False)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"ok": True}


# --------------------------------------------------------------------------- subscription

CLIENT_UA = ("happ", "v2ray", "xray", "hiddify", "streisand", "clash", "sing-box", "nekobox", "v2box", "shadowrocket")


def _wants_html(request: Request) -> bool:
    ua = request.headers.get("user-agent", "").lower()
    if any(c in ua for c in CLIENT_UA):
        return False
    return "text/html" in request.headers.get("accept", "")


@app.get("/sub/{token}")
def subscription(token: str, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.sub_token == token))
    if not user:
        raise HTTPException(404)
    if _wants_html(request):
        sub_url = f"{settings.panel_url}/sub/{user.sub_token}"
        return templates.TemplateResponse(
            request,
            "subscription.html",
            {"user": user, "sub_url": sub_url, "settings": settings, "active": user.is_active(), "now": utcnow()},
        )
    body = "\n".join(subscription_lines(user, visible_nodes(db)))
    return PlainTextResponse(base64.b64encode(body.encode()).decode(), headers=subscription_headers(user))


# --------------------------------------------------------------------------- node agent API


def current_node(authorization: str = Header(""), db: Session = Depends(get_db)) -> Node:
    token = authorization.removeprefix("Bearer ").strip()
    node = db.scalar(select(Node).where(Node.token == token)) if token else None
    if not node:
        raise HTTPException(401, "bad node token")
    return node


@app.get("/api/node/config")
def node_config(node: Node = Depends(current_node), db: Session = Depends(get_db)):
    node.last_seen = utcnow()
    db.commit()
    users = active_users(db) if node.enabled else []
    return build_config(node, users, node_bridges(db, node))


@app.post("/api/node/stats")
def node_stats(payload: dict, node: Node = Depends(current_node), db: Session = Depends(get_db)):
    record_traffic(db, payload.get("users", {}))
    return {"ok": True}


@app.get("/node/install.sh")
def install_script():
    return FileResponse(NODE_FILES / "install.sh", media_type="text/plain")


@app.get("/node/agent.py")
def agent_script():
    return FileResponse(NODE_FILES / "agent.py", media_type="text/plain")
