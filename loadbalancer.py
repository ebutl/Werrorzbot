"""loadbalancer.py — Admin panel VPS/Heroku load balancer management + live monitor"""

import logging
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from config import OWNER_ID, BOT_NAME, API_TIMEOUT
from database import (get_all_load_balancers, add_load_balancer,
    toggle_load_balancer, remove_load_balancer, get_active_load_balancers, is_db_admin)
from emojis import PremiumEmoji as E
from ui import primary, success, danger

logger = logging.getLogger(__name__)

# In-memory status cache: lb_id -> {"ping": ms, "status": "online"/"offline", "checked": datetime}
_lb_status: dict[int, dict] = {}


async def _ping_lb(url: str) -> tuple[bool, float]:
    """Ping a load balancer URL. Returns (online, latency_ms)."""
    start = asyncio.get_event_loop().time()
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as resp:
                latency = (asyncio.get_event_loop().time() - start) * 1000
                return True, round(latency, 1)
    except Exception:
        latency = (asyncio.get_event_loop().time() - start) * 1000
        return False, round(latency, 1)


async def refresh_lb_status():
    """Refresh status of all load balancers."""
    lbs = get_all_load_balancers()
    for lb in lbs:
        online, ms = await _ping_lb(lb["url"])
        _lb_status[lb["id"]] = {
            "ping": ms,
            "status": "online" if online else "offline",
            "checked": datetime.now().strftime("%H:%M:%S")
        }


def _lb_panel_text(uid: int) -> str:
    lbs = get_all_load_balancers()
    text = (f"<blockquote>{E.SPEED} <b>Load Balancers</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n")

    if not lbs:
        text += f"{E.INFO} <i>No load balancers added yet.</i>\n"
    else:
        for lb in lbs:
            st = _lb_status.get(lb["id"], {})
            status_icon = E.APPROVED if st.get("status") == "online" else E.DECLINED
            enabled_icon = "🟢" if lb["enabled"] else "🔴"
            ping = st.get("ping", "?")
            checked = st.get("checked", "—")
            text += (f"{enabled_icon} <b>[{lb['id']}] {lb['name']}</b>\n"
                     f"  {E.GLOBE} <code>{lb['url']}</code>\n"
                     f"  {status_icon} {st.get('status', 'unknown').upper()}  |  "
                     f"⚡ {ping}ms  |  🕐 {checked}\n"
                     f"  Provider: <code>{lb.get('provider','vps')}</code>\n"
                     f"━━━━━━━━━━━━━━━━━━\n")

    text += f"{E.INFO} API Timeout: <code>{API_TIMEOUT}s</code>"
    return text


def _lb_keyboard(uid: int):
    lbs = get_all_load_balancers()
    rows = []
    for lb in lbs:
        enabled = lb["enabled"]
        toggle_label = "🔴 Disable" if enabled else "🟢 Enable"
        rows.append([
            primary(f"[{lb['id']}] {lb['name'][:12]}", f"lb_info_{lb['id']}"),
            success(toggle_label, f"lb_toggle_{lb['id']}"),
            danger("🗑", f"lb_remove_{lb['id']}"),
        ])
    rows.append([
        success("+ Add VPS", "lb_add_vps"),
        success("+ Add Heroku", "lb_add_heroku"),
        primary("🔄 Refresh", "lb_refresh"),
    ])
    rows.append([primary("Back", "menu_admin")])
    return InlineKeyboardMarkup(rows)


async def lb_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    if uid != OWNER_ID and not is_db_admin(uid):
        await q.answer("Admin only", show_alert=True)
        return

    try: await q.answer()
    except: pass

    if data == "lb_refresh":
        await q.edit_message_text(f"<blockquote>{E.LOAD} <b>Pinging...</b></blockquote>",
                                   parse_mode="HTML")
        await refresh_lb_status()
        await q.edit_message_text(_lb_panel_text(uid), parse_mode="HTML",
                                   reply_markup=_lb_keyboard(uid))
        return

    if data.startswith("lb_toggle_"):
        lb_id = int(data.split("_")[-1])
        lbs = get_all_load_balancers()
        lb = next((x for x in lbs if x["id"] == lb_id), None)
        if lb:
            toggle_load_balancer(lb_id, not lb["enabled"])
        await q.edit_message_text(_lb_panel_text(uid), parse_mode="HTML",
                                   reply_markup=_lb_keyboard(uid))
        return

    if data.startswith("lb_remove_"):
        lb_id = int(data.split("_")[-1])
        remove_load_balancer(lb_id)
        await q.edit_message_text(_lb_panel_text(uid), parse_mode="HTML",
                                   reply_markup=_lb_keyboard(uid))
        return

    if data in ("lb_add_vps", "lb_add_heroku"):
        provider = "vps" if data == "lb_add_vps" else "heroku"
        context.user_data["lb_add_provider"] = provider
        context.user_data["lb_add_step"] = "name"
        await q.message.reply_text(
            f"<blockquote>{E.INFO} <b>Add {provider.upper()} Load Balancer</b></blockquote>\n\n"
            f"Send: <code>NAME URL</code>\n"
            f"Example: <code>VPS-1 http://1.2.3.4:8081</code>",
            parse_mode="HTML"
        )
        return

    if data == "menu_lb":
        await refresh_lb_status()
        await q.edit_message_text(_lb_panel_text(uid), parse_mode="HTML",
                                   reply_markup=_lb_keyboard(uid))


async def lb_add_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for adding a load balancer."""
    if context.user_data.get("lb_add_step") != "name":
        return
    uid = update.effective_user.id
    if uid != OWNER_ID and not is_db_admin(uid):
        return

    context.user_data.pop("lb_add_step", None)
    provider = context.user_data.pop("lb_add_provider", "vps")
    text = update.message.text.strip()

    parts = text.split(None, 1)
    if len(parts) != 2:
        await update.message.reply_text(
            f"{E.ERROR} Format: <code>NAME URL</code>", parse_mode="HTML")
        return

    name, url = parts
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            f"{E.ERROR} URL must start with http:// or https://", parse_mode="HTML")
        return

    add_load_balancer(name, url, provider)
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Added</b></blockquote>\n"
        f"{E.RIGHT} <b>{name}</b> <code>{url}</code> ({provider})",
        parse_mode="HTML"
    )


def get_lb_panel_text(uid): return _lb_panel_text(uid)
def get_lb_keyboard(uid): return _lb_keyboard(uid)


def register_lb(app):
    from telegram.ext import MessageHandler, filters
    app.add_handler(CallbackQueryHandler(lb_callbacks, pattern=r"^lb_"))
    app.add_handler(CallbackQueryHandler(lb_callbacks, pattern=r"^menu_lb$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, lb_add_text_handler))
