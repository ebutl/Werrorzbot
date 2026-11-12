"""
fb.py — Feedback with premium emojis + approve posts to hit group.
"""

import random
import string
import html
import logging
from datetime import datetime
from typing import Dict, Any

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest, TelegramError

from config import (
    OWNER_ID, HIT_DETECTION_GROUP_ID, OWNER_USERNAME, OWNER_NAME,
)
from emojis import PremiumEmoji as E
from ui import primary, success, danger

logger = logging.getLogger(__name__)

pending_feedbacks: Dict[str, Dict[str, Any]] = {}

def _esc(x):
    return html.escape(str(x)) if x is not None else "None"

def _gen_fid():
    return "FB" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def _utf16_to_py(text: str, offset: int) -> int:
    if offset <= 0: return 0
    raw = text.encode("utf-16-le")
    bo = min(offset * 2, len(raw))
    return len(raw[:bo].decode("utf-16-le", errors="ignore"))

def _detect_premium(text: str, entities) -> str:
    if not text or not entities: return text
    rich = text
    for ent in sorted(entities, key=lambda e: e.offset, reverse=True):
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            s = _utf16_to_py(text, ent.offset)
            e = _utf16_to_py(text, ent.offset + ent.length)
            tag = f'<tg-emoji emoji-id="{ent.custom_emoji_id}">{text[s:e]}</tg-emoji>'
            rich = rich[:s] + tag + rich[e:]
    return rich

def _moderation_card(fb: Dict[str, Any]) -> str:
    uid = fb.get("user_id")
    fn = _esc(fb.get("first_name"))
    un = _esc(fb.get("username") or "None")
    msg = fb.get("rich_text") or "--"
    fid = fb.get("id", "")

    return (
        f"<blockquote>{E.FIRE} <b>New Feedback</b> {E.SPARKLE}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>Name:</b> <a href='tg://user?id={uid}'>{fn}</a>\n"
        f"{E.EMOJI_3} <b>Username:</b> @{un}\n"
        f"{E.KEY} <b>UID:</b> <code>{uid}</code>\n"
        f"{E.NOTE} <b>FB ID:</b> <code>{fid}</code>\n"
        f"{E.CLOCK} <b>Time:</b> <code>{fb.get('timestamp', '')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.NOTE} <b>Message:</b>\n"
        f"{msg}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

def _log_caption(fb: Dict[str, Any]) -> str:
    uid = fb.get("user_id")
    fn = _esc(fb.get("first_name"))
    msg = fb.get("rich_text") or "--"
    fid = fb.get("id", "")

    return (
        f"<blockquote>{E.SUCCESS} <b>Approved Feedback</b> {E.SPARKLE}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>User:</b> <a href='tg://user?id={uid}'>{fn}</a>\n"
        f"{E.KEY} <b>UID:</b> <code>{uid}</code>\n"
        f"{E.NOTE} <b>FB ID:</b> <code>{fid}</code>\n"
        f"{E.CLOCK} <b>Time:</b> <code>{fb.get('timestamp', '')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.NOTE} <b>Message:</b>\n{msg}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

def _mod_kb(fid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [success("Approve", f"fb_approve_{fid}"), danger("Reject", f"fb_reject_{fid}")],
        [danger("Close", f"fb_close_{fid}")],
    ])

async def _send_fb_message(bot, chat_id, fb, caption, kb):
    media_id = fb.get("media_file_id")
    media_type = fb.get("media_type")

    try:
        if media_id and media_type == "photo":
            msg = await bot.send_photo(chat_id=chat_id, photo=media_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            return True, msg
        elif media_id and media_type == "video":
            msg = await bot.send_video(chat_id=chat_id, video=media_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            return True, msg
        else:
            msg = await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=kb)
            return True, msg
    except (BadRequest, TelegramError) as e:
        logger.warning(f"fb send {media_type} fail to {chat_id}: {e}")
        try:
            msg = await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=kb)
            return True, msg
        except Exception as e2:
            logger.error(f"fb text fallback fail to {chat_id}: {e2}")
            return False, None

async def fb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    uid = user.id
    fn = user.first_name
    un = user.username

    text, rich_text, media_id, media_type = "", "", None, None

    if context.args:
        parts = msg.text.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        rich_text = _detect_premium(text, msg.entities)
    elif msg.reply_to_message:
        r = msg.reply_to_message
        if r.photo:
            text, rich_text = r.caption or "", _detect_premium(r.caption or "", r.caption_entities)
            media_id, media_type = r.photo[-1].file_id, "photo"
        elif r.video:
            text, rich_text = r.caption or "", _detect_premium(r.caption or "", r.caption_entities)
            media_id, media_type = r.video.file_id, "video"
        elif r.document:
            text, rich_text = r.caption or "", _detect_premium(r.caption or "", r.caption_entities)
        else:
            text = r.text or r.caption or ""
            rich_text = _detect_premium(text, r.entities or r.caption_entities)
    elif msg.photo:
        text, rich_text = msg.caption or "", _detect_premium(msg.caption or "", msg.caption_entities)
        media_id, media_type = msg.photo[-1].file_id, "photo"
    elif msg.video:
        text, rich_text = msg.caption or "", _detect_premium(msg.caption or "", msg.caption_entities)
        media_id, media_type = msg.video.file_id, "video"

    if not text and not media_id:
        await msg.reply_text(f"<blockquote>{E.INFO} <b>Send Feedback</b> {E.SPARKLE}</blockquote>\n\n{E.RIGHT} <code>/fb your message</code>", parse_mode="HTML")
        return

    fid = _gen_fid()
    fb = {
        "id": fid, "user_id": uid, "first_name": fn, "username": un,
        "text": text, "rich_text": rich_text or text, "media_file_id": media_id,
        "media_type": media_type, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",
    }
    pending_feedbacks[fid] = fb

    await msg.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Feedback Sent</b> {E.SPARKLE}</blockquote>\n"
        f"{E.INFO} <b>ID</b> ➠ <code>{fid}</code>\n\n"
        f"<i>Admins will review soon.</i>", parse_mode="HTML")

    card = _moderation_card(fb)
    kb = _mod_kb(fid)

    owner_sent = False
    try:
        ok, msg_obj = await _send_fb_message(context.bot, OWNER_ID, fb, card, kb)
        owner_sent = ok
    except Exception as e:
        logger.error(f"fb owner DM fail: {e}")

    if not owner_sent:
        try:
            await msg.reply_text(f"⚠️ <b>Notification failed</b>\n\n<i>Contact</i> <a href='https://t.me/{OWNER_USERNAME}'>@{OWNER_USERNAME}</a>", parse_mode="HTML")
        except Exception:
            pass

async def fb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try: await q.answer()
    except Exception: pass

    if q.from_user.id != OWNER_ID:
        try: await q.answer("⛔ Owner only", show_alert=True)
        except Exception: pass
        return

    parts = q.data.split("_", 2)
    if len(parts) < 3: return
    action, fid = parts[1], parts[2]

    fb = pending_feedbacks.get(fid)
    if not fb:
        try: await q.answer("⏰ Not found", show_alert=True)
        except Exception: pass
        return
    if fb.get("status") != "pending":
        try: await q.answer(f"⚠️ Already {fb['status']}", show_alert=True)
        except Exception: pass
        return

    target_uid = fb["user_id"]
    owner_name = q.from_user.first_name

    if action == "close":
        fb["status"] = "closed"
        try: await q.message.delete()
        except Exception: pass
        try: await q.answer("Closed")
        except Exception: pass
        return

    if action == "approve":
        fb["status"] = "approved"
        log_caption = _log_caption(fb)

        posted = False
        try:
            ok, msg_obj = await _send_fb_message(context.bot, HIT_DETECTION_GROUP_ID, fb, log_caption, kb=None)
            posted = ok
            
            # ═══ AUTO PIN TO LOGS GROUP ═══
            if posted and msg_obj:
                try:
                    await context.bot.pin_chat_message(chat_id=HIT_DETECTION_GROUP_ID, message_id=msg_obj.message_id)
                except Exception as pin_e:
                    logger.error(f"Failed to pin approved feedback: {pin_e}")
                    
        except Exception as e:
            logger.error(f"fb approve post fail: {e}")

        if not posted:
            try: await q.answer("⚠️ Post failed", show_alert=True)
            except Exception: pass
            fb["status"] = "pending"
            return

        try:
            await context.bot.send_message(chat_id=target_uid, text=f"<blockquote>{E.APPROVED} <b>Feedback Approved</b> {E.SPARKLE}</blockquote>\n{E.INFO} <b>ID</b> ➠ <code>{fid}</code>\n\n<i>Your feedback has been published!</i>", parse_mode="HTML")
        except Exception: pass

        try:
            await q.message.edit_text(f"<blockquote>{E.APPROVED} <b>Approved</b> {E.SPARKLE}</blockquote>\n\n{E.USER} By: {owner_name}\n{E.INFO} User: {_esc(fb.get('first_name'))} (<code>{target_uid}</code>)\n{E.SUCCESS} Posted to hit group ✅", parse_mode="HTML")
        except Exception: pass

        try: await q.answer("✅ Approved and pinned")
        except Exception: pass
        return

    if action == "reject":
        fb["status"] = "rejected"
        try:
            await context.bot.send_message(chat_id=target_uid, text=f"<blockquote>{E.DECLINED} <b>Feedback Rejected</b></blockquote>\n{E.INFO} <b>ID</b> ➠ <code>{fid}</code>\n\n<i>Your feedback was not approved.</i>", parse_mode="HTML")
        except Exception: pass
        try:
            await q.message.edit_text(f"<blockquote>{E.DECLINED} <b>Rejected</b></blockquote>\n\n{E.USER} By: {owner_name}\n{E.INFO} User: {_esc(fb.get('first_name'))} (<code>{target_uid}</code>)", parse_mode="HTML")
        except Exception: pass
        try: await q.answer("❌ Rejected")
        except Exception: pass
        return

def register_fb(app):
    app.add_handler(CommandHandler("fb", fb_command))
    app.add_handler(CallbackQueryHandler(fb_callback, pattern=r"^fb_"))
    logger.info("✅ /fb registered")