import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database import get_redeem_code_info, delete_redeem_code, is_db_admin
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)


async def delkey(update, context):
    user = update.effective_user
    if user.id != OWNER_ID and not is_db_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML"); return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/delkey KEY</code>", parse_mode="HTML"); return
    key = context.args[0].strip().upper()
    info = get_redeem_code_info(key)
    if not info:
        await update.message.reply_text(f"{E.ERROR} Key not found or used.", parse_mode="HTML"); return
    tier = info.get("tier", "?"); days = info.get("duration_days", 0)
    if not delete_redeem_code(key):
        await update.message.reply_text(f"{E.ERROR} Failed.", parse_mode="HTML"); return
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Key Deleted</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.KEY} <b>Key</b> ➠ <code>{key}</code>\n"
        f"{E.STAR} <b>Tier</b> ➠ <code>{tier}</code>\n"
        f"{E.CLOCK} <b>Days</b> ➠ <code>{days}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML", disable_web_page_preview=True)


def register_delkey(app: Application):
    app.add_handler(CommandHandler("delkey", delkey))