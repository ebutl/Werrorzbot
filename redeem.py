"""redeem.py — Claim codes with owner bypass"""

import logging
import random
import string
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    get_redeem_code_info, mark_redeem_code_as_used,
    save_redeem_code, update_user_plan, update_user_credits,
    get_user_credits, has_user_active_plan, is_db_admin,
)
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
ADMIN_IDS = [OWNER_ID]

PLANS = {
    "Core": {"tier": "Core", "duration_days": 7, "emoji": "🛠️"},
    "Elite": {"tier": "Elite", "duration_days": 15, "emoji": "👑"},
    "Root": {"tier": "Root", "duration_days": 30, "emoji": "⭐"},
    "X": {"tier": "X", "duration_days": 90, "emoji": "💎"},
}

active_requests = {}


def is_admin(uid):
    if uid in ADMIN_IDS: return True
    try: return is_db_admin(uid)
    except: return False


def gen_code(length=16):
    chars = string.ascii_uppercase + string.digits
    return f"CXGFT-{''.join(random.choices(chars, k=length - 5))}"


async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Claim Code</b></blockquote>\n\n"
            f"<code>/claim CXGFT-XXXX</code>",
            parse_mode=ParseMode.HTML)
        return

    code = context.args[0].strip().upper()

    # ═══ Accept both CXGFT- and SPITZ- prefixes ═══
    if not (code.startswith("CXGFT-") or code.startswith("SPITZ-")):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Invalid Format</b></blockquote>\n\n"
            f"{E.INFO} <i>Codes start with CXGFT- or SPITZ-</i>\n"
            f"{E.NOTE} <i>You provided:</i> <code>{code[:20]}</code>",
            parse_mode=ParseMode.HTML)
        return

    uid = update.effective_user.id
    un = update.effective_user.first_name

    if uid in active_requests and active_requests[uid]:
        await update.message.reply_text("⏳ Wait.", parse_mode=ParseMode.HTML)
        return

    active_requests[uid] = True
    proc = await update.message.reply_text(
        f"<blockquote>🔄 <b>Validating...</b></blockquote>\n"
        f"<pre>{code}</pre>",
        parse_mode=ParseMode.HTML)

    try:
        info = get_redeem_code_info(code)
        if not info:
            await proc.edit_text(
                f"<blockquote>{E.ERROR} <b>Invalid Code</b></blockquote>\n\n"
                f"{E.KEY} <b>Code:</b> <code>{code}</code>\n"
                f"{E.INFO} <i>Code invalid or already used.</i>",
                parse_mode=ParseMode.HTML)
            return

        tier = info["tier"]
        dur = info["duration_days"]

        # Credits code
        if tier == "Credits":
            update_user_credits(uid, 100)
            mark_redeem_code_as_used(code, uid)
            await proc.edit_text(
                f"<blockquote>{E.SUCCESS} <b>Redeemed</b></blockquote>\n"
                f"{E.PREMIUM} <b>Type:</b> <code>100 Credits</code>\n"
                f"{E.STATS} <b>Added:</b> <code>+100</code>",
                parse_mode=ParseMode.HTML)
            return

        # ═══ Owner bypasses active-plan check ═══
        if uid != OWNER_ID and has_user_active_plan(uid):
            await proc.edit_text(
                f"<blockquote>{E.ERROR} <b>Active Plan</b></blockquote>\n\n"
                f"{E.INFO} <i>You already have an active plan.</i>",
                parse_mode=ParseMode.HTML)
            return

        exp = datetime.now() + timedelta(days=dur)
        success = update_user_plan(uid, tier, exp)

        if success:
            mark_redeem_code_as_used(code, uid)
            pi = PLANS.get(tier, {"emoji": "⭐"})
            emoji = pi["emoji"]
            await proc.edit_text(
                f"<blockquote>{E.SUCCESS} <b>Redeemed</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.KEY} <b>Code:</b> <code>{code}</code>\n"
                f"{E.STAR} <b>Tier:</b> {emoji} <code>{tier}</code>\n"
                f"{E.CLOCK} <b>Days:</b> <code>{dur}</code>\n"
                f"{E.CALANDER} <b>Expires:</b> <code>{exp.strftime('%Y-%m-%d %H:%M')}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.APPROVED} <b>Unlimited credits</b>\n"
                f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
                parse_mode=ParseMode.HTML)
        else:
            await proc.edit_text(
                f"<blockquote>{E.ERROR} <b>Failed</b></blockquote>\n"
                f"{E.NOTE} <i>DB error</i>",
                parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"claim: {e}")
        try:
            await proc.edit_text(f"{E.ERROR} {e}", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        active_requests[uid] = False


async def handle_gplan1(update, context): await _gen_plan(update, context, "Core")
async def handle_gplan2(update, context): await _gen_plan(update, context, "Elite")
async def handle_gplan3(update, context): await _gen_plan(update, context, "Root")
async def handle_gplan4(update, context): await _gen_plan(update, context, "X")


async def _gen_plan(update, context, tier):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text("<code>/gplan N</code>", parse_mode=ParseMode.HTML)
        return
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50: raise ValueError
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Count 1-50.", parse_mode=ParseMode.HTML)
        return

    plan = PLANS.get(tier)
    if not plan: return

    codes = []
    for _ in range(count):
        c = gen_code()
        if save_redeem_code(c, plan["tier"], plan["duration_days"]):
            codes.append(c)
    ct = "\n".join(f"<code>{c}</code>" for c in codes)
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Codes Generated</b></blockquote>\n"
        f"{E.STAR} <b>Tier:</b> {plan['emoji']} {tier}\n"
        f"{E.STATS} <b>Count:</b> <code>{len(codes)}</code>\n\n"
        f"<pre>{ct}</pre>",
        parse_mode=ParseMode.HTML)


async def handle_gcodes(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text("<code>/gcodes N</code>", parse_mode=ParseMode.HTML)
        return
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50: raise ValueError
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Count 1-50.", parse_mode=ParseMode.HTML)
        return
    codes = []
    for _ in range(count):
        c = gen_code()
        if save_redeem_code(c, "Credits", 0): codes.append(c)
    ct = "\n".join(f"<code>{c}</code>" for c in codes)
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Credits Codes</b></blockquote>\n"
        f"{E.PREMIUM} <b>Type:</b> <code>100 Credits</code>\n"
        f"{E.STATS} <b>Count:</b> <code>{len(codes)}</code>\n\n"
        f"<pre>{ct}</pre>",
        parse_mode=ParseMode.HTML)