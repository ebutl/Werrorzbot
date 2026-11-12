"""plans.py — Plan management (plan1-4, rplan, planall, decreds)"""

import logging
import random
import string
import os
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from database import (
    get_or_create_user, update_user_plan, get_user_plan,
    get_user_credits, update_user_credits, get_all_active_plans,
    is_db_admin,
)
from emojis import PremiumEmoji as E
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME, HIT_DETECTION_GROUP_ID

logger = logging.getLogger(__name__)
ADMIN_IDS = [OWNER_ID]
LOG_CHANNEL_ID = HIT_DETECTION_GROUP_ID

PLANS = {
    "plan1": {"name": "Core Access",  "tier": "Core",  "duration_days": 7,  "emoji": "🛠️", "price": "$8.00"},
    "plan2": {"name": "Elite Access", "tier": "Elite", "duration_days": 15, "emoji": "👑", "price": "$14.00"},
    "plan3": {"name": "Root Access",  "tier": "Root",  "duration_days": 30, "emoji": "⭐", "price": "$25.00"},
    "plan4": {"name": "X-Access",     "tier": "X",     "duration_days": 90, "emoji": "💎", "price": "$60.00"},
}


def is_admin(user_id):
    if user_id in ADMIN_IDS: return True
    try: return is_db_admin(user_id)
    except: return False


def _fmt_plan_resp(ok, name, uid, uname, tier, days, emoji, err=None):
    if ok:
        exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        return (f"<blockquote>{E.SUCCESS} <b>Plan Updated</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.USER} <b>User</b> ➠ <a href='tg://user?id={uid}'>{uname}</a>\n"
                f"{E.STAR} <b>Plan</b> ➠ {emoji} {name}\n"
                f"{E.STATS} <b>Tier</b> ➠ <code>{tier}</code>\n"
                f"{E.CLOCK} <b>Days</b> ➠ <code>{days}d</code>\n"
                f"{E.CALANDER} <b>Expires</b> ➠ <code>{exp}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")
    return f"<blockquote>{E.ERROR} <b>Failed</b></blockquote>\n{E.NOTE} <code>{err}</code>"


def _fmt_congrats(uid, uname, name, tier, days, emoji):
    exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    return (f"<blockquote>{E.SPARKLE} <b>Congratulations!</b> {E.FIRE}</blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.USER} <b>{uname}</b>\n"
            f"{E.STAR} <b>Plan</b> ➠ {emoji} {name}\n"
            f"{E.STATS} <b>Tier</b> ➠ <code>{tier}</code>\n"
            f"{E.CLOCK} <b>Days</b> ➠ <code>{days}d</code>\n"
            f"{E.CALANDER} <b>Expires</b> ➠ <code>{exp}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.APPROVED} <b>Unlimited credits</b> until expiry\n"
            f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")


async def handle_plan_command(update, context, plan_type):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(f"<code>/{plan_type} UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid UID.", parse_mode="HTML")
        return

    info = PLANS.get(plan_type)
    if not info:
        await update.message.reply_text(f"{E.ERROR} Invalid plan.", parse_mode="HTML")
        return

    try:
        target = await context.bot.get_chat(uid)
        target_name = target.first_name or "Unknown"
    except Exception:
        target_name = "Unknown"

    expiry = datetime.now() + timedelta(days=info["duration_days"])
    ok = update_user_plan(uid, info["tier"], expiry)

    if ok:
        try:
            await context.bot.send_message(chat_id=uid,
                text=_fmt_congrats(uid, target_name, info["name"], info["tier"],
                                   info["duration_days"], info["emoji"]),
                parse_mode="HTML")
        except Exception:
            pass

    await update.message.reply_text(
        _fmt_plan_resp(ok, info["name"], uid, target_name, info["tier"],
                       info["duration_days"], info["emoji"]),
        parse_mode="HTML")


async def handle_plan1(update, context): await handle_plan_command(update, context, "plan1")
async def handle_plan2(update, context): await handle_plan_command(update, context, "plan2")
async def handle_plan3(update, context): await handle_plan_command(update, context, "plan3")
async def handle_plan4(update, context): await handle_plan_command(update, context, "plan4")


async def handle_rplan(update, context):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return
    if not context.args:
        await update.message.reply_text(f"<code>/rplan UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return

    plan = get_user_plan(uid)
    if not plan:
        await update.message.reply_text(f"{E.WARNING} No active plan.", parse_mode="HTML")
        return
    tier, _ = plan
    ok = update_user_plan(uid, "Trial", None)

    if ok:
        try:
            await context.bot.send_message(chat_id=uid,
                text=(f"<blockquote>{E.WARNING} <b>Plan Ended</b></blockquote>\n"
                      f"{E.NOTE} <b>{tier}</b> revoked. Reverted to Trial."),
                parse_mode="HTML")
        except Exception:
            pass

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS if ok else E.ERROR} <b>Revoked</b></blockquote>\n"
        f"{E.USER} UID ➠ <code>{uid}</code>",
        parse_mode="HTML")


async def handle_planall(update, context):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    plans = get_all_active_plans()
    if not plans:
        await update.message.reply_text(f"<blockquote>{E.INFO} No active plans</blockquote>",
                                         parse_mode="HTML")
        return

    lines = ["ACTIVE PLANS", f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Total: {len(plans)}", "=" * 40, ""]
    for uid, tier, exp in plans:
        try:
            u = await context.bot.get_chat(uid)
            uname = u.first_name or "Unknown"
        except Exception:
            uname = "Unknown"
        lines += [f"User: {uname}", f"UID: {uid}", f"Tier: {tier}",
                  f"Expires: {exp:%Y-%m-%d %H:%M}", "-" * 40]

    fname = f"active_plans_{datetime.now():%Y%m%d_%H%M%S}.txt"
    try:
        with open(fname, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        with open(fname, "rb") as f:
            await update.message.reply_document(document=f,
                caption=f"<blockquote>{E.STATS} <b>Active Plans</b></blockquote>\n"
                        f"<i>Total: {len(plans)} users</i>",
                parse_mode="HTML")
    except Exception as e:
        logger.error(f"planall: {e}")
        await update.message.reply_text(f"{E.ERROR} Failed.", parse_mode="HTML")
    finally:
        if os.path.exists(fname): os.remove(fname)


async def handle_decreds(update, context):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return
    if len(context.args) < 2:
        await update.message.reply_text(f"<code>/decreds UID N</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0]); amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return
    if amount <= 0:
        await update.message.reply_text(f"{E.ERROR} Amount > 0.", parse_mode="HTML")
        return

    cur = get_user_credits(uid)
    if cur is None:
        await update.message.reply_text(f"{E.ERROR} User not found.", parse_mode="HTML")
        return
    if cur == float("inf"):
        await update.message.reply_text(f"{E.WARNING} Unlimited.", parse_mode="HTML")
        return

    if not update_user_credits(uid, -amount):
        await update.message.reply_text(f"{E.ERROR} DB fail.", parse_mode="HTML")
        return

    new = get_user_credits(uid)
    try:
        u = await context.bot.get_chat(uid); uname = u.first_name or "Unknown"
    except Exception:
        uname = "Unknown"

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Credits Updated</b></blockquote>\n"
        f"{E.USER} <b>User</b> ➠ <a href='tg://user?id={uid}'>{uname}</a>\n"
        f"{E.PREMIUM} <b>Deducted</b> ➠ <code>-{amount}</code>\n"
        f"{E.STATS} <b>Balance</b> ➠ <code>{new}</code>",
        parse_mode="HTML")


def check_plan_expiry(user_id):
    plan = get_user_plan(user_id)
    if not plan: return None
    tier, exp = plan
    if exp and datetime.now() > exp:
        update_user_plan(user_id, "Trial", None)
        return "Trial"
    return tier


def get_user_current_tier(user_id):
    # Owner & admins get their role
    try:
        from config import OWNER_ID
        if user_id == OWNER_ID: return "Owner"
        if is_db_admin(user_id): return "Admin"
    except Exception:
        pass

    tier = check_plan_expiry(user_id)
    if tier is None:
        data = get_or_create_user(user_id, None)
        if data:
            _, _, tier, _ = data
    return tier or "Trial"