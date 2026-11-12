"""speed.py — MSH speed control (OWNER ONLY)"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from database import get_msh_speed, set_msh_speed
from emojis import PremiumEmoji as E
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME

logger = logging.getLogger(__name__)

HARD_MAX = 20
RECOMMENDED_MAX = 2


def _is_owner(uid):
    return uid == OWNER_ID


async def speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not _is_owner(user.id):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Owner Only</b></blockquote>\n\n"
            f"<i>This command is restricted to the owner.</i>",
            parse_mode="HTML")
        return

    if not context.args:
        current = get_msh_speed()
        await update.message.reply_text(
            f"<blockquote>{E.SITES} <b>MSH Speed</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.STATS} <b>Current:</b> <code>{current}</code>\n"
            f"{E.SHIELD} <b>Hard Cap:</b> <code>{HARD_MAX}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.INFO} <i>Lower = slower, API friendly</i>\n"
            f"{E.INFO} <i>Higher = faster, API stress</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.NOTE} <b>Change:</b> <code>/speed 2</code>\n"
            f"{E.WARNING} <i>Anything above {HARD_MAX} auto-clamped</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
            parse_mode="HTML")
        return

    try:
        speed = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Invalid value</b></blockquote>\n\n"
            f"<i>Must be a number between 1-{HARD_MAX}</i>",
            parse_mode="HTML")
        return

    if speed < 1:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Minimum 1</b></blockquote>",
            parse_mode="HTML")
        return

    clamped = speed
    note = ""
    if speed > HARD_MAX:
        clamped = HARD_MAX
        note = f"\n{E.WARNING} <i>Clamped {speed} → {HARD_MAX} (hard cap)</i>"

    set_msh_speed(clamped)

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Speed Updated</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.SITES} <b>New Speed:</b> <code>{clamped}</code> ✅{note}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.INFO} <i>Active checks not affected</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML")
    logger.info(f"MSH speed set to {clamped} by owner {user.id}")


async def msh_speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await speed_command(update, context)


def register_speed(app):
    app.add_handler(CommandHandler("speed", speed_command))
    app.add_handler(CommandHandler("mshspeed", msh_speed_command))
    logger.info("✅ /speed registered (owner only)")