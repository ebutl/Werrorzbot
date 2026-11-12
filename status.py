import time, socket, platform, logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from database import connection_pool, get_total_users
from config import OWNER_USERNAME, OWNER_NAME

logger = logging.getLogger(__name__)
from emojis import PremiumEmoji as _PE
BULLET = _PE.RIGHT; BPT = _PE.RIGHT; ARW = "↬"; DIV = "――――――――――――――"
BOT_START = time.time()


def _uptime():
    try:
        import psutil
        up = int(time.time() - psutil.boot_time())
    except: up = 0
    d, r = divmod(up, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
    return f"{d}d {h:02}:{m:02}:{s:02}"


def _bot_uptime():
    up = int(time.time() - BOT_START)
    d, r = divmod(up, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
    return f"{d}d {h:02}:{m:02}:{s:02}"


def _bar(pct, length=10):
    f = int(length * pct / 100)
    return '█' * f + '░' * (length - f) + f" {pct:.1f}%"


def _sys():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        dsk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        return {
            "cpu": cpu, "cores": psutil.cpu_count(),
            "mem": mem.percent, "mem_used": mem.used/(1024**3), "mem_total": mem.total/(1024**3),
            "disk": dsk.percent, "disk_used": dsk.used/(1024**3), "disk_total": dsk.total/(1024**3),
            "sent": net.bytes_sent/(1024**2), "recv": net.bytes_recv/(1024**2),
            "host": socket.gethostname(), "os": platform.system(),
            "os_v": platform.version().split("-")[0], "arch": platform.machine(),
            "uptime": _uptime(), "bot_uptime": _bot_uptime(),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "start": datetime.fromtimestamp(BOT_START).strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


def _build(info, users):
    if info.get("error"):
        return f"{BULLET} Error: <code>{info['error']}</code>"
    return (
        f"{BULLET} <b>𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬</b> {ARW} <code>✅ Active</code>\n"
        f"{DIV}\n"
        f"{BULLET} <b>Users</b> {ARW} <code>{users}</code>\n"
        f"{BULLET} <b>Bot Uptime</b> {ARW} <code>{info['bot_uptime']}</code>\n"
        f"{BULLET} <b>System Uptime</b> {ARW} <code>{info['uptime']}</code>\n"
        f"{BULLET} <b>Restart</b> {ARW} <code>{info['start']}</code>\n"
        f"{BULLET} <b>Now</b> {ARW} <code>{info['now']}</code>\n"
        f"{DIV}\n"
        f"{BULLET} <b>OS</b> {ARW} <code>{info['os']} {info['os_v']}</code>\n"
        f"{BULLET} <b>Arch</b> {ARW} <code>{info['arch']}</code>\n"
        f"{BULLET} <b>Host</b> {ARW} <code>{info['host']}</code>\n"
        f"{DIV}\n"
        f"{BULLET} <b>CPU</b> {ARW} <code>{info['cpu']:.1f}% ({info['cores']} cores)</code>\n"
        f"{BPT} {_bar(info['cpu'])}\n"
        f"{BULLET} <b>RAM</b> {ARW} <code>{info['mem_used']:.1f}/{info['mem_total']:.1f}GB</code>\n"
        f"{BPT} {_bar(info['mem'])}\n"
        f"{BULLET} <b>Disk</b> {ARW} <code>{info['disk_used']:.1f}/{info['disk_total']:.1f}GB</code>\n"
        f"{BPT} {_bar(info['disk'])}\n"
        f"{BULLET} <b>Net</b> {ARW} <code>↑{info['sent']:.0f}MB ↓{info['recv']:.0f}MB</code>\n"
        f"{DIV}\n"
        f"{BULLET} <b>By</b> {ARW} <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )


async def status_command(update, context):
    info = _sys(); users = get_total_users()
    text = _build(info, users)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def refresh_status_callback(update, context):
    q = update.callback_query
    await q.answer("Refreshing...")
    info = _sys(); users = get_total_users()
    text = _build(info, users)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]])
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


def register_status_handlers(app):
    app.add_handler(CallbackQueryHandler(refresh_status_callback, pattern="refresh_status"))