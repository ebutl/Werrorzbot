"""profile.py — /id, /profile, /info"""

import html
import logging
from datetime import datetime
import pytz

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from database import (
    get_or_create_user, get_user_credits, is_db_admin, is_user_banned,
    get_user_plan, get_user_all_time_stats,  # <-- Stats import kiya
)
from plans import get_user_current_tier
from emojis import PremiumEmoji as E
from ui import primary, danger
from anime_image import get_anime_image
from config import (
    OWNER_ID, OWNER_USERNAME, OWNER_NAME, BOT_NAME,
    ANIME_FALLBACK, GC_LINK, UPDATES_LINK,
)

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _fmt_dt(dt):
    if dt is None:
        return "Unknown"
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(IST).strftime("%d/%m/%y %H:%M:%S")


def _profile_kb(user_id):
    from emojis import ButtonEmoji as BE
    is_admin = (user_id == OWNER_ID or is_db_admin(user_id))
    rows = [
        [primary("Gates", "menu_gates", icon=BE.GATES),
         primary("Tools", "menu_tools", icon=BE.SETTINGS_EMOJI)],
        [primary("Commands", "menu_commands", icon=BE.SEARCH),
         primary("Pricing", "menu_pricing", icon=BE.PRICING)],
    ]
    if is_admin:
        rows.append([danger("Admin Panel", "menu_admin", icon=BE.ADMIN)])
    rows.append([primary("Group", url=GC_LINK, icon=BE.GROUP),
                 primary("Updates", url=UPDATES_LINK, icon=BE.UPDATES)])
    rows.append([primary("Dev", url="https://t.me/CARDERxRDX", icon=BE.DEV),
                 primary("Support", url="https://t.me/CARDERxRDX", icon=BE.SUPPORT)])
    rows.append([danger("Close", "close_menu", icon=BE.CLOSE)])
    return InlineKeyboardMarkup(rows)


def _profile_caption(user, dd):
    uid = user.id
    db_u, db_j, db_t, db_c = dd
    
    # Credits nikal rahe hain
    credits = get_user_credits(uid)
    cds = "Infinite😎" if credits == float("inf") else str(db_c)
    fj = _fmt_dt(db_j)
    du = f"@{html.escape(db_u)}" if db_u else "None"
    ef = html.escape(user.first_name or "User")

    # Stats aur Plan nikal rahe hain
    stats = get_user_all_time_stats(uid)
    plan = get_user_plan(uid)
    
    plan_text = "Trial / No Plan"
    if plan:
        p_tier, p_exp = plan
        if p_exp:
            plan_text = f"{p_tier} (Exp: {_fmt_dt(p_exp)})"

    return (
        f"<blockquote>{E.FIRE} <b>{BOT_NAME}</b> {E.SPARKLE}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>Chat ID</b> ➠ <code>{uid}</code>\n"
        f"{E.EMOJI_3} <b>Username</b> ➠ {du}\n"
        f"{E.EMOJI_2} <b>Name</b> ➠ <a href='tg://user?id={uid}'>{ef}</a> <code>[{html.escape(db_t)}]</code>\n"
        f"{E.PREMIUM} <b>Credits</b> ➠ <code>{cds}</code>\n"
        f"{E.STAR} <b>Active Plan</b> ➠ <code>{plan_text}</code>\n"
        f"{E.FIRE} <b>Total Charges</b> ➠ <code>{stats['charged']}</code>\n"
        f"{E.APPROVED} <b>Approved Cards</b> ➠ <code>{stats['approved']}</code>\n"
        f"{E.CALANDER} <b>Joined</b> ➠ <code>{fj}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    un = user.username
    
    # ═══ FIX: DB Error handling ═══
    try:
        dd = get_or_create_user(uid, un)
    except Exception as e:
        logger.error(f"DB Error in profile: {e}")
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>DB Busy</b></blockquote>\n\n"
            f"{E.INFO} <i>Database is locked. Try again in 2 seconds.</i>",
            parse_mode="HTML")
        return
        
    if not dd:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>DB Error</b></blockquote>\n\n"
            f"{E.INFO} <i>Try /start first</i>",
            parse_mode="HTML")
        return

    caption = _profile_caption(user, dd)
    kb = _profile_kb(uid)

    try:
        image_url = await get_anime_image()
    except Exception:
        image_url = ANIME_FALLBACK

    try:
        await update.message.reply_photo(
            photo=image_url, caption=caption,
            parse_mode="HTML", reply_markup=kb)
    except Exception:
        try:
            await update.message.reply_photo(
                photo=ANIME_FALLBACK, caption=caption,
                parse_mode="HTML", reply_markup=kb)
        except Exception:
            await update.message.reply_text(
                caption, parse_mode="HTML", reply_markup=kb)
    logger.info(f"/profile -> {uid}")


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed info. Owner/admin can look up other users."""
    requester = update.effective_user
    target_id = requester.id

    if context.args:
        if requester.id != OWNER_ID and not is_db_admin(requester.id):
            await update.message.reply_text(
                f"<blockquote>{E.ERROR} <b>Admin only</b></blockquote>\n\n"
                f"<i>Only admins can look up other users.</i>",
                parse_mode="HTML")
            return
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                f"<blockquote>{E.ERROR} <b>Invalid ID</b></blockquote>",
                parse_mode="HTML")
            return

    try:
        dd = get_or_create_user(target_id, None)
    except Exception as e:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>DB Busy</b></blockquote>\n\n"
            f"{E.INFO} <i>Try again.</i>",
            parse_mode="HTML")
        return

    if not dd:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>User not found</b></blockquote>",
            parse_mode="HTML")
        return

    db_u, db_j, db_t, db_c = dd
    tier = get_user_current_tier(target_id)
    credits = get_user_credits(target_id)
    cds = "Infinite😎" if credits == float("inf") else str(db_c)
    is_admin = (target_id == OWNER_ID or is_db_admin(target_id))
    banned = is_user_banned(target_id)
    plan = get_user_plan(target_id)

    premium_display = "None"
    if plan:
        p_tier, p_exp = plan
        if p_exp:
            premium_display = f"{p_tier} until {_fmt_dt(p_exp)}"

    role = "Owner" if target_id == OWNER_ID else ("Admin" if is_admin else "User")
    status = "Banned ❌" if banned else "Active ✅"

    text = (
        f"<blockquote>{E.SEARCH} <b>Account Info</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>Name</b> ➠ <a href='tg://user?id={target_id}'>{html.escape(str(db_u or 'Unknown'))}</a>\n"
        f"{E.EMOJI_4} <b>ID</b> ➠ <code>{target_id}</code>\n"
        f"{E.EMOJI_3} <b>Username</b> ➠ @{html.escape(str(db_u or 'None'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.STAR} <b>Tier</b> ➠ <code>{html.escape(tier)}</code>\n"
        f"{E.PREMIUM} <b>Credits</b> ➠ <code>{cds}</code>\n"
        f"{E.SHIELD} <b>Role</b> ➠ <code>{role}</code>\n"
        f"{E.STATS} <b>Status</b> ➠ <code>{status}</code>\n"
        f"{E.CALANDER} <b>Premium</b> ➠ <code>{premium_display}</code>\n"
        f"{E.CLOCK} <b>Joined</b> ➠ <code>{_fmt_dt(db_j)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


def register_profile(app):
    app.add_handler(CommandHandler("id", profile_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("info", info_command))
    logger.info("✅ /profile registered")