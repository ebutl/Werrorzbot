import logging
from typing import Dict
from datetime import datetime
import pytz

from database import get_or_create_user, get_user_credits
from plans import get_user_current_tier
from config import OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')


def format_indian_datetime(dt):
    if dt.tzinfo is None: dt = pytz.utc.localize(dt)
    return dt.astimezone(IST).strftime('%d/%m/%y %H:%M:%S')


def format_credits_response(user_info):
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    try:
        ud = get_or_create_user(user_id, username)
        if not ud:
            tier = "Unknown"; joined = datetime.now()
        else: _, joined, tier, _ = ud
    except Exception:
        tier = "Unknown"; joined = datetime.now()
    try:
        c = get_user_credits(user_id)
        if c is None: credits_display = "Error"
        elif c == float('inf'): credits_display = "Infinite😎"
        else: credits_display = str(c)
    except Exception: credits_display = "Error"
    try:
        ut = get_user_current_tier(user_id)
        if ut: tier = ut
    except Exception: pass
    fj = format_indian_datetime(joined)
    if credits_display == "Infinite😎": cs = "🔥"
    elif credits_display == "Error": cs = "❌"
    elif credits_display.isdigit():
        n = int(credits_display); cs = "✅" if n>50 else ("⚠️" if n>10 else "🔴")
    else: cs = "❌"
    ul = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{tier}]</code>"
    return (f"<blockquote>{E.USER} <b>𝑼𝒔𝒆𝒓 𝑰𝒏𝒇𝒐</b></blockquote>\n"
            f"{E.RIGHT} <b>𝐈𝐃</b> ↬ <code>{user_id}</code>\n"
            f"{E.RIGHT} <b>𝐔𝐬𝐞𝐫</b> ↬ @{username if username else 'None'}\n"
            f"{E.RIGHT} <b>𝐍𝐚𝐦𝐞</b> ↬ {ul}\n"
            f"{E.RIGHT} <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code> {cs}\n"
            f"{E.RIGHT} <b>𝐉𝐨𝐢𝐧𝐞𝐝</b> ↬ <code>{fj}</code>\n"
            f"{E.LINK} <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")


async def handle_credits_command(update, context):
    user_id = update.effective_user.id
    r = format_credits_response({
        "id": user_id,
        "username": update.effective_user.username,
        "first_name": update.effective_user.first_name,
    })
    await update.message.reply_text(r, parse_mode="HTML")