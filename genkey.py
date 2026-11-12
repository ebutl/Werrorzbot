"""genkey.py — Generate keys in 𒉼𝔢𝔯𝔯𝔬𝔯乙-XXXX-XXXX format"""

import secrets, string, logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes

from config import OWNER_ID, BOT_NAME
from database import save_redeem_code, is_db_admin
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
ALPHABET = string.ascii_uppercase + string.digits
VALID_TIERS = {"Core", "Elite", "Root", "X"}


def gen_key():
    """𒉼𝔢𝔯𝔯𝔬𝔯乙-XXXX-XXXX"""
    part1 = "".join(secrets.choice(ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(ALPHABET) for _ in range(4))
    return f"𒉼𝔢𝔯𝔯𝔬𝔯乙-{part1}-{part2}"


async def genkey(update, context):
    user = update.effective_user
    if user.id != OWNER_ID and not is_db_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Generate Key</b></blockquote>\n\n"
            f"<b>Usage:</b> <code>/genkey DAYS TIER</code>\n"
            f"<b>Tiers:</b> Core, Elite, Root, X\n\n"
            f"<b>Examples:</b>\n"
            f"<code>/genkey 7 Core</code>\n"
            f"<code>/genkey 30 Root</code>",
            parse_mode="HTML")
        return

    try:
        days = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Days must be number.", parse_mode="HTML")
        return

    tier = context.args[1].strip().title()
    if tier not in VALID_TIERS:
        await update.message.reply_text(
            f"{E.ERROR} Invalid tier.\nUse: <code>Core</code> <code>Elite</code> <code>Root</code> <code>X</code>",
            parse_mode="HTML")
        return

    if days <= 0 or days > 365:
        await update.message.reply_text(f"{E.ERROR} Days 1-365.", parse_mode="HTML")
        return

    key = gen_key()
    if not save_redeem_code(key, tier, days):
        await update.message.reply_text(f"{E.ERROR} Failed to save.", parse_mode="HTML")
        return

    try:
        me = await context.bot.get_me()
        bot_user = me.username
    except Exception:
        bot_user = None

    redeem = f"https://t.me/{bot_user}?start=redeem_{key}" if bot_user else None

    text = (f"<blockquote>{E.KEY} <b>Key Generated</b> {E.SPARKLE}</blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.KEY} <b>Key</b> ➠ <code>{key}</code>\n"
            f"{E.STAR} <b>Tier</b> ➠ <code>{tier}</code>\n"
            f"{E.CLOCK} <b>Days</b> ➠ <code>{days}</code>\n"
            f"{E.SUCCESS} <b>Status</b> ➠ Ready\n")
    if redeem:
        text += f"\n<b>Redeem:</b> <code>{redeem}</code>\n"
    text += f"\n<b>Claim:</b> <code>/claim {key}</code>\n"
    text += f"━━━━━━━━━━━━━━━━━━\n{E.LINK} <b>Dev</b> ➠ {BOT_NAME}"

    await update.message.reply_text(text, parse_mode="HTML")


def register_genkey(app):
    app.add_handler(CommandHandler("genkey", genkey))
