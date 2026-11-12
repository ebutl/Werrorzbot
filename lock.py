from telegram import Update, LinkPreviewOptions
from telegram.ext import CommandHandler, ContextTypes
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database import is_bot_locked, set_bot_lock
from emojis import PremiumEmoji as E
import logging

logger = logging.getLogger(__name__)

async def lock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Owner Only</b></blockquote>",
            parse_mode="HTML")
        return

    if is_bot_locked():
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘽𝙊𝙏 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Bot is currently in lock mode.

Use /unlock to unlock the bot.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    set_bot_lock(True)
    logger.info(f"Bot locked by {user.id}")

    await update.message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝘽𝙊𝙏 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.LOCK} Bot is now in maintenance mode.

All commands are temporarily disabled.

Use /unlock to restore normal operation.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

async def unlock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Owner Only</b></blockquote>",
            parse_mode="HTML")
        return

    if not is_bot_locked():
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘽𝙊𝙏 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Bot is already in normal operation mode.

Use /lock to lock the bot if needed.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    set_bot_lock(False)
    logger.info(f"Bot unlocked by {user.id}")

    await update.message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝘽𝙊𝙏 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.FLY} Bot is now back to normal operation.

All commands are now available.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

def register_lock_commands(app):
    app.add_handler(CommandHandler("lock", lock_bot))
    app.add_handler(CommandHandler("unlock", unlock_bot))
    logger.info("✅ Lock commands registered.")