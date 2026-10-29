"""Settings, read once from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field


def _plans(raw: str) -> list[tuple[int, int]]:
    """'30:150,90:400' -> [(30, 150), (90, 400)]  (days, price in Telegram Stars)."""
    plans = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            days, price = part.split(":")
            plans.append((int(days), int(price)))
    return plans


@dataclass(frozen=True)
class Settings:
    panel_url: str = os.getenv("PANEL_URL", "http://localhost:8000").rstrip("/")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/vpn.db")
    secret_key: str = os.getenv("SECRET_KEY", "change-me")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")

    brand_name: str = os.getenv("BRAND_NAME", "MyVPN")
    support_url: str = os.getenv("SUPPORT_URL", "")
    announce: str = os.getenv("ANNOUNCE", "")
    update_interval_hours: int = int(os.getenv("SUB_UPDATE_HOURS", "6"))

    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_tg_ids: tuple[int, ...] = tuple(
        int(x) for x in os.getenv("ADMIN_TG_IDS", "").replace(" ", "").split(",") if x
    )
    trial_days: int = int(os.getenv("TRIAL_DAYS", "3"))
    referral_bonus_days: int = int(os.getenv("REFERRAL_BONUS_DAYS", "7"))
    plans: list[tuple[int, int]] = field(
        default_factory=lambda: _plans(os.getenv("PLANS", "30:150,90:400,180:750,365:1400"))
    )

    # A node that has not checked in for this long is shown as offline and
    # hidden from subscriptions so clients never get a dead server.
    node_offline_after_sec: int = int(os.getenv("NODE_OFFLINE_AFTER_SEC", "300"))


settings = Settings()
