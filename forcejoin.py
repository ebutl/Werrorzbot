"""
forcejoin.py — Force-join with direct pass for joined users + cache
"""

from functools import wraps
import logging
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import (
    FORCE_JOIN_GROUP_ID, FORCE_JOIN_GROUP_LINK,
    FORCE_JOIN_CHANNEL_ID, FORCE_JOIN_CHANNEL_LINK,
    FORCE_JOIN_IMAGE,
)
from anime_image import get_anime_image

logger = logging.getLogger("force_join")

# Cache: user_id -> (status, expires_at)
# status: True (joined) / False (not joined)
_JOIN_CACHE = {}
_CACHE_TTL = 30  # seconds — joined users skip API for 30s


def _cache_get(uid):
    entry = _JOIN_CACHE.get(uid)
    if not entry:
        return None
    ok, exp = entry
    if time.time() > exp:
        _JOIN_CACHE.pop(uid, None)
        return None
    return ok


def _cache_set(uid, ok, ttl=_CACHE_TTL):
    _JOIN_CACHE[uid] = (ok, time.time() + ttl)


def _cache_invalidate(uid):
    _JOIN_CACHE.pop(uid, None)


async def _member(bot, chat_id, user_id):
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status
    except Exception as e:
        logger.warning(f"get_chat_member fail {user_id}@{chat_id}: {e}")
        return None


async def is_user_joined(bot, user_id, use_cache=True):
    # Banned check
    try:
        from database import is_user_banned
        if is_user_banned(user_id):
            return False
    except Exception:
        pass

    # Cache hit
    if use_cache:
        cached = _cache_get(user_id)
        if cached is not None:
            return cached

    valid = ("member", "administrator", "creator")

    group_status = await _member(bot, FORCE_JOIN_GROUP_ID, user_id)
    if group_status not in valid:
        _cache_set(user_id, False, ttl=10)  # short cache for not-joined
        return False

    channel_status = await _member(bot, FORCE_JOIN_CHANNEL_ID, user_id)
    if channel_status not in valid:
        _cache_set(user_id, False, ttl=10)
        return False

    # Both joined → long cache
    _cache_set(user_id, True, ttl=_CACHE_TTL)
    return True


async def _send_join_prompt(target, reply_markup):
    caption_text = (
        "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 "
        "𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 👇\n\n"
        "🔒 𝗔𝗹𝗹 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 𝗮𝗿𝗲 𝗿𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗲𝗱.\n"
        "✅ 𝗝𝗼𝗶𝗻 𝗯𝗼𝘁𝗵 𝘁𝗼 𝘂𝗻𝗹𝗼𝗰𝗸."
    )

    anime_url = None
    try:
        anime_url = await get_anime_image()
    except Exception as e:
        logger.warning(f"anime fetch fail: {e}")

    sent = False
    for img in (anime_url, FORCE_JOIN_IMAGE):
        if not img:
            continue
        try:
            await target.reply_photo(
                photo=img,
                caption=caption_text,
                reply_markup=reply_markup,
            )
            sent = True
            break
        except Exception as e:
            logger.warning(f"join photo fail ({str(img)[:30]}): {e}")
            continue

    if not sent:
        try:
            await target.reply_text(caption_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"join text fail: {e}")


def force_join(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if not update.effective_user:
            return

        # /start always allowed
        if update.message and update.message.text and update.message.text.startswith("/start"):
            return await func(update, context, *args, **kwargs)

        user_id = update.effective_user.id

        # Check join (cached)
        try:
            joined = await is_user_joined(context.bot, user_id)
        except Exception as e:
            logger.error(f"join check error: {e}")
            joined = False

        # ── Already joined → DIRECT PASS ──
        if joined:
            return await func(update, context, *args, **kwargs)

        # ── Not joined → send prompt ──
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Group", url=f"https://t.me/{FORCE_JOIN_GROUP_LINK}")],
            [InlineKeyboardButton("📡 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL_LINK}")],
            [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")],
        ])

        target = update.message or (
            update.callback_query.message if update.callback_query else None
        )
        if not target:
            return

        await _send_join_prompt(target, reply_markup)

    return wrapper


async def check_joined_callback(update, context):
    q = update.callback_query
    if not q or not q.from_user:
        return

    uid = q.from_user.id
    _cache_invalidate(uid)  # force recheck

    joined = await is_user_joined(context.bot, uid, use_cache=False)

    if joined:
        await q.answer("✅ Access granted! You can now use the bot.", show_alert=True)
        try:
            await q.edit_message_caption(
                "✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲!\n\n"
                "🎉 You have successfully joined the group & channel.\n"
                "🚀 Enjoy using the bot!"
            )
        except Exception:
            pass
    else:
        await q.answer("❌ You still need to join both!", show_alert=True)