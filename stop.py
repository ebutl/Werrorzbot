import logging, time
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, Application
from msh import active_mass_checks as msh_checks
from msh import format_stopped_response as msh_stopped
from emojis import PremiumEmoji as E
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database import is_db_admin

logger = logging.getLogger(__name__)

def _is_admin(uid):
    return uid == OWNER_ID or is_db_admin(uid)

async def handle_stop_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    first = update.effective_user.first_name
    if not context.args:
        sessions = [s for s, d in msh_checks.items() if d.get("user_id") == user_id]
        if not sessions:
            await update.message.reply_text(f"{E.INFO} No active sessions.", parse_mode="HTML")
            return
        sl = "\n".join(f"• <code>{s}</code>" for s in sessions)
        await update.message.reply_text(f"<blockquote>{E.INFO} <b>Your Sessions</b></blockquote>\n\n{sl}\n\n<i>/stop ID</i>", parse_mode="HTML")
        return
    session_id = context.args[0].upper()
    if session_id not in msh_checks:
        await update.message.reply_text(f"{E.ERROR} Not found.", parse_mode="HTML")
        return
    if msh_checks[session_id]["user_id"] != user_id:
        await update.message.reply_text(f"{E.ERROR} Denied.", parse_mode="HTML")
        return

    msh_checks[session_id]["stopped"] = True
    ev = msh_checks[session_id].get("stop_event")
    if ev: ev.set()
    for t in msh_checks[session_id].get("workers", []):
        if not t.done(): t.cancel()

    st = msh_checks[session_id].get("start_time", time.time())
    elapsed = round(abs(time.time() - st), 2)
    stats = msh_checks[session_id].get("stats", {"total": 0, "checked": 0, "charged": 0, "approved": 0, "declined": 0, "error": 0})
    chat_id = msh_checks[session_id].get("chat_id")
    mid = msh_checks[session_id].get("message_id")

    if chat_id and mid:
        try: await context.bot.edit_message_text(chat_id=chat_id, message_id=mid, text=msh_stopped(stats, elapsed, first, session_id), parse_mode="HTML", disable_web_page_preview=True, reply_markup=None)
        except Exception: pass

    await update.message.reply_text(f"<blockquote>{E.SUCCESS} <b>Stopped</b></blockquote>\n{E.KEY} Session ➠ <code>{session_id}</code>\n{E.STATS} Checked ➠ <code>{stats['checked']}/{stats['total']}</code>\n{E.CLOCK} Elapsed ➠ <code>{elapsed}s</code>", parse_mode="HTML")

async def handle_session_command(update: Update, context: CallbackContext):
    if not _is_admin(update.effective_user.id): return
    if not msh_checks:
        await update.message.reply_text(f"<blockquote>{E.INFO} <b>No active sessions</b></blockquote>", parse_mode="HTML"); return
    now = time.time()
    lines = []
    for sid, d in msh_checks.items():
        stats = d.get("stats", {}); uid = d.get("user_id", "?"); started = d.get("start_time", now)
        elapsed = int(now - started); mins, secs = divmod(elapsed, 60)
        processed = stats.get("processed", 0); total = stats.get("total", 0); pct = (processed / total * 100) if total else 0.0
        lines.append(f"{E.KEY} <code>{sid}</code>\n   {E.USER} User: <code>{uid}</code>\n   {E.STATS} Progress: <code>{processed}/{total}</code> ({pct:.1f}%)\n   {E.FIRE} Charged: <code>{stats.get('charged', 0)}</code> | {E.APPROVED} Approved: <code>{stats.get('approved', 0)}</code>\n   {E.CLOCK} Time: <code>{mins}m {secs}s</code>")
    text = f"<blockquote>{E.STATS} <b>Active Sessions</b> ({len(msh_checks)})</blockquote>\n" + "━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(lines) + f"\n━━━━━━━━━━━━━━━━━━\n{E.INFO} <code>/stopsession SID</code> to force stop\n{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    await update.message.reply_text(text, parse_mode="HTML")

async def handle_stopsession_command(update: Update, context: CallbackContext):
    if not _is_admin(update.effective_user.id): return
    if not context.args: await update.message.reply_text(f"<blockquote>{E.INFO} <code>/stopsession SID</code></blockquote>", parse_mode="HTML"); return
    sid = context.args[0].upper()
    if sid not in msh_checks: await update.message.reply_text(f"<blockquote>{E.ERROR} <b>Not found</b></blockquote>\n<code>{sid}</code>", parse_mode="HTML"); return
    d = msh_checks[sid]; d["stopped"] = True
    if d.get("stop_event"): d["stop_event"].set()
    for t in d.get("workers", []):
        if not t.done(): t.cancel()
    await update.message.reply_text(f"<blockquote>{E.SUCCESS} <b>Force Stopped</b></blockquote>\n{E.KEY} SID ➠ <code>{sid}</code>", parse_mode="HTML")

def register_stop(app: Application):
    app.add_handler(CommandHandler("stop", handle_stop_command))
    app.add_handler(CommandHandler("session", handle_session_command))
    app.add_handler(CommandHandler("stopsession", handle_stopsession_command))
