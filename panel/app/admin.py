import hmac
import secrets
import uuid as uuidlib
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Node, Payment, User, utcnow

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
router = APIRouter(prefix="/admin")
GB = 1024**3


def fmt_bytes(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(n) < 1024 or unit == "ТБ":
            return f"{n:.1f} {unit}" if unit != "Б" else f"{n} {unit}"
        n /= 1024
    return str(n)


templates.env.filters["bytes"] = fmt_bytes


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(303, headers={"Location": "/admin/login"})


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"settings": settings, "now": utcnow(), **ctx})


def back(url: str = "/admin") -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --------------------------------------------------------------------------- auth


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if hmac.compare_digest(password.encode(), settings.admin_password.encode()):
        request.session["admin"] = True
        return back()
    return render(request, "login.html", error="Неверный пароль")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return back("/admin/login")


# --------------------------------------------------------------------------- users


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def dashboard(request: Request, q: str = "", db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.id.desc())
    if q:
        like = f"%{q}%"
        conds = [User.username.ilike(like), User.note.ilike(like)]
        if q.isdigit():
            conds += [User.id == int(q), User.telegram_id == int(q)]
        stmt = stmt.where(or_(*conds))
    users = db.scalars(stmt.limit(300)).all()
    now = utcnow()
    all_users = db.scalars(select(User)).all()
    stats = {
        "users": len(all_users),
        "active": sum(1 for u in all_users if u.is_active(now)),
        "nodes_online": sum(1 for n in db.scalars(select(Node)).all() if n.is_online(now)),
        "nodes": db.scalar(select(func.count(Node.id))),
        "revenue_30d": db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.created_at >= now - timedelta(days=30))
        ),
        "traffic": sum(u.used_total for u in all_users),
    }
    return render(request, "dashboard.html", users=users, stats=stats, q=q)


@router.post("/users", dependencies=[Depends(require_admin)])
def create_user(
    username: str = Form(""),
    days: int = Form(30),
    traffic_gb: float = Form(0),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = User(username=username, note=note, traffic_limit=int(traffic_gb * GB), expires_at=utcnow())
    if days > 0:
        user.extend(days)
    else:
        user.expires_at = None  # 0 days = never expires
    db.add(user)
    db.commit()
    return back()


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    return user


@router.post("/users/{user_id}/extend", dependencies=[Depends(require_admin)])
def extend_user(user_id: int, days: int = Form(...), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    user.extend(days)
    db.commit()
    return back()


@router.post("/users/{user_id}/toggle", dependencies=[Depends(require_admin)])
def toggle_user(user_id: int, db: Session = Depends(get_db)):
    user = _user(db, user_id)
    user.enabled = not user.enabled
    db.commit()
    return back()


@router.post("/users/{user_id}/reset-traffic", dependencies=[Depends(require_admin)])
def reset_traffic(user_id: int, db: Session = Depends(get_db)):
    user = _user(db, user_id)
    user.used_up = user.used_down = 0
    db.commit()
    return back()


@router.post("/users/{user_id}/regenerate", dependencies=[Depends(require_admin)])
def regenerate(user_id: int, db: Session = Depends(get_db)):
    """Revoke a leaked link: new subscription URL and new UUID (old configs stop working)."""
    user = _user(db, user_id)
    user.sub_token = secrets.token_urlsafe(16)
    user.uuid = str(uuidlib.uuid4())
    db.commit()
    return back()


@router.post("/users/{user_id}/delete", dependencies=[Depends(require_admin)])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    db.delete(_user(db, user_id))
    db.commit()
    return back()


# --------------------------------------------------------------------------- nodes


@router.get("/nodes", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def nodes_page(request: Request, db: Session = Depends(get_db)):
    nodes = db.scalars(select(Node).order_by(Node.sort, Node.id)).all()
    return render(request, "nodes.html", nodes=nodes)


def _node_form(node: Node, form: dict, db: Session) -> None:
    node.name = form["name"].strip() or "Server"
    node.flag = form.get("flag", "").strip() or "🌐"
    node.address = form["address"].strip()
    node.port = int(form.get("port") or 443)
    node.xhttp_port = int(form.get("xhttp_port") or 0)
    node.sni = form.get("sni", "").strip() or "www.microsoft.com"
    node.sort = int(form.get("sort") or 100)
    node.enabled = form.get("enabled") == "on"
    upstream = int(form.get("upstream_id") or 0)
    if upstream and (upstream == node.id or not db.get(Node, upstream)):
        raise HTTPException(400, "Некорректная вышестоящая нода")
    node.upstream_id = upstream or None
    if node.port == node.xhttp_port:
        raise HTTPException(400, "Порты Vision и XHTTP должны различаться")


@router.post("/nodes", dependencies=[Depends(require_admin)])
async def create_node(request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    form.setdefault("enabled", "on")
    node = Node(name="", address="")
    _node_form(node, form, db)
    db.add(node)
    db.commit()
    return back(f"/admin/nodes/{node.id}")


@router.get("/nodes/{node_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def node_page(node_id: int, request: Request, db: Session = Depends(get_db)):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404)
    others = db.scalars(select(Node).where(Node.id != node_id, Node.upstream_id.is_(None))).all()
    install = (
        f"curl -fsSL {settings.panel_url}/node/install.sh | "
        f"sudo bash -s -- {settings.panel_url} {node.token}"
    )
    return render(request, "node_edit.html", node=node, others=others, install=install)


@router.post("/nodes/{node_id}", dependencies=[Depends(require_admin)])
async def update_node(node_id: int, request: Request, db: Session = Depends(get_db)):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404)
    _node_form(node, dict(await request.form()), db)
    db.commit()
    return back(f"/admin/nodes/{node.id}")


@router.post("/nodes/{node_id}/delete", dependencies=[Depends(require_admin)])
def delete_node(node_id: int, db: Session = Depends(get_db)):
    node = db.get(Node, node_id)
    if node:
        for child in db.scalars(select(Node).where(Node.upstream_id == node.id)).all():
            child.upstream_id = None
        db.delete(node)
        db.commit()
    return back("/admin/nodes")


# --------------------------------------------------------------------------- payments


@router.get("/payments", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def payments_page(request: Request, db: Session = Depends(get_db)):
    payments = db.scalars(select(Payment).order_by(Payment.id.desc()).limit(500)).all()
    return render(request, "payments.html", payments=payments)
