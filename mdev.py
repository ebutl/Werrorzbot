"""mdev.py — /mdev command: users contact dev privately, forwarded silently"""

import logging
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import DEV_ID, BOT_NAME
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)

# user_id -> message_id of their /mdev init message
_pending_mdev: dict[int, bool] = {}


async def mdev_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    # If args provided, send directly
    if context.args:
        text = " ".join(context.args)
        await _forward_to_dev(context, uid, user.username, text, None)
        await update.message.reply_text(
            f"<blockquote>{E.SUCCESS} <b>Message Sent</b></blockquote>\n"
            f"{E.INFO} Dev will respond shortly.",
            parse_mode="HTML"
        )
        return

    # Prompt for reply
    _pending_mdev[uid] = True
    await update.message.reply_text(
        f"<blockquote>{E.INFO} <b>Contact Dev</b></blockquote>\n\n"
        f"Send your message, reply to an image, or attach a file.\n"
        f"{E.RIGHT} Type your message now:",
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True)
    )


async def mdev_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    msg = update.message

    if not _pending_mdev.get(uid):
        return

    # Only handle if it's a reply to the bot's message or a direct text
    _pending_mdev.pop(uid, None)

    text = msg.text or msg.caption or ""
    file_id = None
    file_type = None

    if msg.photo:
        file_id = msg.photo[-1].file_id; file_type = "photo"
    elif msg.document:
        file_id = msg.document.file_id; file_type = "document"

    await _forward_to_dev(context, uid, user.username, text, file_id, file_type)
    await msg.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Sent to Dev</b></blockquote>\n"
        f"{E.INFO} Message forwarded. Dev will respond.",
        parse_mode="HTML"
    )


async def _forward_to_dev(context, uid, username, text, file_id, file_type=None):
    header = (
        f"📩 <b>User Message</b>\n"
        f"ID: <code>{uid}</code>  @{username or 'none'}\n"
        f"{'─'*20}\n"
        f"{text or '(no text)'}"
    )
    try:
        if file_type == "photo" and file_id:
            await context.bot.send_photo(chat_id=DEV_ID, photo=file_id, caption=header, parse_mode="HTML")
        elif file_type == "document" and file_id:
            await context.bot.send_document(chat_id=DEV_ID, document=file_id, caption=header, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=DEV_ID, text=header, parse_mode="HTML")
    except Exception as e:
        logger.error(f"mdev forward: {e}")


def register_mdev(app):
    app.add_handler(CommandHandler("mdev", mdev_command))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.Document.ALL) & filters.ChatType.PRIVATE & filters.REPLY,
        mdev_reply_handler
    ))
