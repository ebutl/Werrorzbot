import asyncio, logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest, RetryAfter
from database import get_all_user_ids
from config import OWNER_ID
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
SLEEP_TIME = 0.09
PROGRESS_EVERY = 25
broadcast_task = None


async def broad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global broadcast_task
    if update.effective_user.id != OWNER_ID: return
    if broadcast_task and not broadcast_task.done():
        await update.message.reply_text(f"{E.WARNING} Broadcast running.", parse_mode="HTML"); return
    message = None
    if context.args: message = " ".join(context.args)
    elif update.message.reply_to_message: message = update.message.reply_to_message
    if not message:
        await update.message.reply_text(f"<code>/broad MSG</code>", parse_mode="HTML"); return
    user_ids = get_all_user_ids()
    if not user_ids:
        await update.message.reply_text(f"{E.WARNING} No users.", parse_mode="HTML"); return
    status_msg = await update.message.reply_text(
        f"<blockquote>{E.FIRE} <b>Broadcast Started</b></blockquote>\n"
        f"👥 <b>Total</b> ➠ <code>{len(user_ids)}</code>\n"
        f"📨 <b>Sent</b> ➠ <code>0</code>\n"
        f"🚫 <b>Blocked</b> ➠ <code>0</code>\n"
        f"⚠️ <b>Errors</b> ➠ <code>0</code>", parse_mode="HTML")
    broadcast_task = asyncio.create_task(_worker(context.bot, status_msg, user_ids, message))


async def _worker(bot, status_msg, user_ids, message):
    sent = blocked = errors = 0
    total = len(user_ids); last = 0
    for idx, uid in enumerate(user_ids, 1):
        try:
            if isinstance(message, str): await bot.send_message(chat_id=uid, text=message)
            else: await message.copy(chat_id=uid)
            sent += 1
        except Forbidden: blocked += 1
        except BadRequest: errors += 1
        except RetryAfter as e: await asyncio.sleep(e.retry_after); continue
        except Exception: errors += 1
        await asyncio.sleep(SLEEP_TIME)
        if idx - last >= PROGRESS_EVERY or idx == total:
            last = idx
            try:
                await status_msg.edit_text(
                    f"<blockquote>{E.FIRE} <b>Broadcasting...</b></blockquote>\n"
                    f"👥 <b>Total</b> ➠ <code>{total}</code>\n"
                    f"📨 <b>Sent</b> ➠ <code>{sent}</code>\n"
                    f"🚫 <b>Blocked</b> ➠ <code>{blocked}</code>\n"
                    f"⚠️ <b>Errors</b> ➠ <code>{errors}</code>", parse_mode="HTML")
            except: pass
    try:
        await status_msg.edit_text(
            f"<blockquote>{E.SUCCESS} <b>Complete</b></blockquote>\n"
            f"👥 <b>Total</b> ➠ <code>{total}</code>\n"
            f"📨 <b>Sent</b> ➠ <code>{sent}</code>\n"
            f"🚫 <b>Blocked</b> ➠ <code>{blocked}</code>\n"
            f"⚠️ <b>Errors</b> ➠ <code>{errors}</code>", parse_mode="HTML")
    except: pass