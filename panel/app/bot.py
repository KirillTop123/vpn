"""Telegram sales bot: free trial, payments in Telegram Stars, subscription delivery, referrals.

Run: python -m app.bot
"""
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from sqlalchemy import select

from .config import settings
from .db import SessionLocal, init_db
from .models import User, utcnow
from .services import apply_payment, get_or_create_tg_user, start_trial

log = logging.getLogger("bot")
router = Router()


def sub_url(user: User) -> str:
    return f"{settings.panel_url}/sub/{user.sub_token}"


def status_text(user: User) -> str:
    if user.is_active():
        until = user.expires_at.strftime("%d.%m.%Y %H:%M UTC") if user.expires_at else "бессрочно"
        return f"✅ Подписка активна до <b>{until}</b>"
    return "❌ Подписка не активна"


def menu(user: User) -> InlineKeyboardMarkup:
    rows = []
    if not user.trial_used and settings.trial_days:
        rows.append([InlineKeyboardButton(text=f"🎁 Попробовать бесплатно {settings.trial_days} дн.", callback_data="trial")])
    rows += [
        [InlineKeyboardButton(text="💳 Купить / продлить", callback_data="buy")],
        [InlineKeyboardButton(text="🔑 Моя подписка", callback_data="sub")],
        [
            InlineKeyboardButton(text="📱 Как подключить", callback_data="howto"),
            InlineKeyboardButton(text="👥 Пригласить", callback_data="ref"),
        ],
    ]
    if settings.support_url:
        rows.append([InlineKeyboardButton(text="🆘 Поддержка", url=settings.support_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_keyboard(user: User) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Подключить в Happ", url=sub_url(user))],
            [InlineKeyboardButton(text="💳 Продлить", callback_data="buy")],
            [InlineKeyboardButton(text="« Меню", callback_data="menu")],
        ]
    )


def sub_text(user: User) -> str:
    return (
        f"{status_text(user)}\n\n"
        f"Ваша ссылка-подписка (нажмите, чтобы скопировать):\n<code>{sub_url(user)}</code>\n\n"
        "Нажмите «Подключить в Happ» — откроется страница с кнопкой добавления в приложение."
    )


async def edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:  # "message is not modified" on a double tap
        if "not modified" not in str(e):
            raise
    await cb.answer()


def load_user(tg_id: int, username: str = "") -> User:
    with SessionLocal() as db:
        user, _ = get_or_create_tg_user(db, tg_id, username)
        return user


# --------------------------------------------------------------------------- user flow


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    with SessionLocal() as db:
        user, created = get_or_create_tg_user(
            db, message.from_user.id, message.from_user.username or message.from_user.full_name, command.args
        )
    text = (
        f"👋 Добро пожаловать в <b>{settings.brand_name}</b>!\n\n"
        "• Быстрые серверы в разных странах\n"
        "• Работает при «белых списках» на мобильном интернете\n"
        "• Обходит блокировки и замедления (VLESS Reality / XHTTP)\n"
        "• Приложение Happ: iPhone, Android, Windows, macOS\n\n"
        f"{status_text(user)}"
    )
    await message.answer(text, reply_markup=menu(user))


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery):
    user = load_user(cb.from_user.id)
    await edit(cb, f"<b>{settings.brand_name}</b>\n\n{status_text(user)}", menu(user))


@router.callback_query(F.data == "trial")
async def cb_trial(cb: CallbackQuery):
    with SessionLocal() as db:
        user, _ = get_or_create_tg_user(db, cb.from_user.id, cb.from_user.username or "")
        ok = start_trial(db, user)
    if not ok:
        await cb.answer("Пробный период уже был использован", show_alert=True)
        return
    await edit(cb, f"🎁 Пробный период активирован!\n\n{sub_text(user)}", sub_keyboard(user))


@router.callback_query(F.data == "sub")
async def cb_sub(cb: CallbackQuery):
    user = load_user(cb.from_user.id)
    await edit(cb, sub_text(user), sub_keyboard(user))


@router.callback_query(F.data == "howto")
async def cb_howto(cb: CallbackQuery):
    text = (
        "📱 <b>Как подключиться</b>\n\n"
        "1. Установите <b>Happ</b>:\n"
        "   • iPhone/Mac — App Store\n"
        "   • Android — Google Play\n"
        "   • Windows — happ.su\n"
        "2. Откройте «🔑 Моя подписка» → «Подключить в Happ».\n"
        "3. В Happ выберите сервер и нажмите кнопку подключения.\n\n"
        "💡 Если на мобильном интернете работают только сайты из «белого списка» — выбирайте серверы "
        "с пометкой «Белые списки». Если сервер не работает, попробуйте вариант XHTTP или другую страну."
    )
    await edit(cb, text, InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Меню", callback_data="menu")]]
    ))


@router.callback_query(F.data == "ref")
async def cb_ref(cb: CallbackQuery, bot: Bot):
    user = load_user(cb.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={user.id}"
    text = (
        "👥 <b>Приглашайте друзей</b>\n\n"
        f"За каждого друга, который оплатит подписку, вы получите <b>+{settings.referral_bonus_days} дней</b>.\n\n"
        f"Ваша ссылка:\n<code>{link}</code>"
    )
    await edit(cb, text, InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Меню", callback_data="menu")]]
    ))


# --------------------------------------------------------------------------- payments (Telegram Stars)


def plan_title(days: int) -> str:
    return {30: "1 месяц", 90: "3 месяца", 180: "6 месяцев", 365: "1 год"}.get(days, f"{days} дней")


@router.callback_query(F.data == "buy")
async def cb_buy(cb: CallbackQuery):
    rows = [
        [InlineKeyboardButton(text=f"{plan_title(days)} — {price} ⭐", callback_data=f"plan:{days}")]
        for days, price in settings.plans
    ]
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu")])
    await edit(
        cb,
        "💳 <b>Выберите тариф</b>\n\nОплата звёздами Telegram ⭐ — их можно купить прямо в Telegram "
        "картой или через App Store / Google Play.\nВсе серверы и устройства включены.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def find_plan(days: int) -> int | None:
    return next((price for d, price in settings.plans if d == days), None)


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(cb: CallbackQuery):
    days = int(cb.data.split(":")[1])
    price = find_plan(days)
    if price is None:
        await cb.answer("Тариф недоступен", show_alert=True)
        return
    await cb.message.answer_invoice(
        title=f"{settings.brand_name}: {plan_title(days)}",
        description=f"Доступ ко всем серверам на {days} дней",
        payload=f"sub:{days}:{price}",
        currency="XTR",
        prices=[LabeledPrice(label=plan_title(days), amount=price)],
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    try:
        _, days, price = q.invoice_payload.split(":")
        ok = find_plan(int(days)) == int(price) == q.total_amount and q.currency == "XTR"
    except ValueError:
        ok = False
    await q.answer(ok=ok, error_message=None if ok else "Тариф изменился, попробуйте ещё раз")


@router.message(F.successful_payment)
async def paid(message: Message, bot: Bot):
    sp = message.successful_payment
    days = int(sp.invoice_payload.split(":")[1])
    with SessionLocal() as db:
        user, _ = get_or_create_tg_user(db, message.from_user.id, message.from_user.username or "")
        referrer = apply_payment(db, user, days, sp.total_amount, sp.currency, sp.telegram_payment_charge_id)
        user = db.get(User, user.id)
    await message.answer(f"✅ Оплата получена, спасибо!\n\n{sub_text(user)}", reply_markup=sub_keyboard(user))
    if referrer and referrer.telegram_id:
        await safe_send(bot, referrer.telegram_id,
                        f"🎉 Ваш друг оплатил подписку — вам начислено +{settings.referral_bonus_days} дней!")
    for admin_id in settings.admin_tg_ids:
        await safe_send(bot, admin_id, f"💰 Оплата {sp.total_amount} ⭐ · {days} дн. · #{user.id} @{user.username}")


async def safe_send(bot: Bot, chat_id: int, text: str, **kw) -> bool:
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except Exception as e:  # blocked bot, deleted account, etc.
        log.info("send to %s failed: %s", chat_id, e)
        return False


# --------------------------------------------------------------------------- admin commands


def is_admin(message: Message) -> bool:
    return message.from_user.id in settings.admin_tg_ids


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message):
        return
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        now = utcnow()
        active = sum(1 for u in users if u.is_active(now))
    await message.answer(f"👤 Всего: {len(users)}\n✅ Активных: {active}\n\nАдминка: {settings.panel_url}/admin")


@router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject):
    """/give <telegram_id> <days>"""
    if not is_admin(message):
        return
    try:
        tg_id, days = (int(x) for x in (command.args or "").split())
    except ValueError:
        await message.answer("Использование: /give <telegram_id> <дней>")
        return
    with SessionLocal() as db:
        user, _ = get_or_create_tg_user(db, tg_id, "")
        user.extend(days)
        db.commit()
    await message.answer(f"Готово: #{user.id} до {user.expires_at:%d.%m.%Y}")
    await safe_send(message.bot, tg_id, f"🎁 Вам начислено {days} дней подписки!")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject):
    """/broadcast <text> — message every user of the bot."""
    if not is_admin(message) or not command.args:
        return
    with SessionLocal() as db:
        ids = [u.telegram_id for u in db.scalars(select(User).where(User.telegram_id.is_not(None))).all()]
    sent = 0
    for tg_id in ids:
        sent += await safe_send(message.bot, tg_id, command.args)
        await asyncio.sleep(0.05)  # stay under Telegram's ~30 msg/s limit
    await message.answer(f"Отправлено: {sent} из {len(ids)}")


# --------------------------------------------------------------------------- expiry reminders


async def reminder_loop(bot: Bot):
    while True:
        try:
            await send_reminders(bot)
        except Exception:
            log.exception("reminders failed")
        await asyncio.sleep(3600)


async def send_reminders(bot: Bot):
    now = utcnow()
    with SessionLocal() as db:
        due = db.scalars(
            select(User).where(
                User.telegram_id.is_not(None),
                User.enabled,
                User.expires_at.is_not(None),
                User.expires_at > now,
                User.expires_at < now + timedelta(days=1),
            )
        ).all()
        for user in due:
            if user.reminded_for == user.expires_at:
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Продлить", callback_data="buy")]])
            await safe_send(bot, user.telegram_id, "⏰ Подписка заканчивается менее чем через сутки. Продлите, "
                            "чтобы не остаться без доступа.", reply_markup=kb)
            user.reminded_for = user.expires_at
        db.commit()


async def main():
    logging.basicConfig(level=logging.INFO)
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")
    init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
