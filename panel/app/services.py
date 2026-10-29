"""Business logic shared by the web panel and the Telegram bot."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import Node, Payment, User, utcnow


def visible_nodes(db: Session) -> list[Node]:
    """Nodes that go into client subscriptions: enabled and recently heard from."""
    nodes = db.scalars(select(Node).where(Node.enabled).order_by(Node.sort, Node.id)).all()
    now = utcnow()
    return [n for n in nodes if n.is_online(now)]


def active_users(db: Session) -> list[User]:
    now = utcnow()
    return [u for u in db.scalars(select(User).where(User.enabled)).all() if u.is_active(now)]


def node_bridges(db: Session, node: Node) -> list[Node]:
    return list(db.scalars(select(Node).where(Node.upstream_id == node.id, Node.enabled)).all())


def record_traffic(db: Session, stats: dict[str, dict[str, int]]) -> None:
    """stats = {"u12": {"up": 123, "down": 456}, "bridge3": {...}}; bridge counters are ignored
    because the same bytes were already counted per user on the bridge node."""
    ids = {}
    for email, v in stats.items():
        if email.startswith("u") and email[1:].isdigit():
            ids[int(email[1:])] = v
    if not ids:
        return
    for user in db.scalars(select(User).where(User.id.in_(ids))).all():
        v = ids[user.id]
        user.used_up += max(0, int(v.get("up", 0)))
        user.used_down += max(0, int(v.get("down", 0)))
    db.commit()


def get_or_create_tg_user(db: Session, tg_id: int, username: str, ref_code: str | None = None) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.telegram_id == tg_id))
    if user:
        if username and user.username != username:
            user.username = username
            db.commit()
        return user, False
    user = User(telegram_id=tg_id, username=username or "", enabled=True, expires_at=utcnow())
    if ref_code and ref_code.isdigit():
        referrer = db.get(User, int(ref_code))
        if referrer and referrer.telegram_id != tg_id:
            user.referred_by = referrer.id
    db.add(user)
    db.commit()
    return user, True


def start_trial(db: Session, user: User) -> bool:
    if user.trial_used:
        return False
    user.trial_used = True
    user.extend(settings.trial_days)
    db.commit()
    return True


def apply_payment(db: Session, user: User, days: int, amount: int, currency: str, charge_id: str) -> User | None:
    """Extend the subscription. Idempotent per charge_id. Returns the referrer if they got a bonus."""
    db.add(Payment(user_id=user.id, days=days, amount=amount, currency=currency, provider_charge_id=charge_id))
    user.extend(days)
    referrer = None
    if user.referred_by and not user.referral_rewarded and settings.referral_bonus_days:
        referrer = db.get(User, user.referred_by)
        if referrer:
            referrer.extend(settings.referral_bonus_days)
            user.referral_rewarded = True
    try:
        db.commit()
    except IntegrityError:  # same charge delivered twice
        db.rollback()
        return None
    return referrer
