import re, random, time, logging, asyncio, html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME, BOT_NAME, HIT_DETECTION_GROUP_ID
from database import get_active_proxy_strings, is_db_admin, set_jio_number, get_jio_number, set_jio_ban, get_jio_ban
from plans import get_user_current_tier
from emojis import PremiumEmoji as E
from bin import get_bin_info
from ui import primary, success, danger
from jio_core import run_jio

logger = logging.getLogger(__name__)
JIO_CHK_SESSIONS = {}
NAP_EVERY = 10
NAP_DURATION = 300
BAN_DURATION = 86400

def fmt_prog(stats, sid):
    return (f"<blockquote>{E.FIRE} <b>JIO MASS CHECKER</b> {E.SPARKLE}</blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.KEY} <b>Session:</b> <code>{sid}</code>\n"
            f"{E.STATS} <b>Progress:</b> <code>{stats.get('processed', 0)}/{stats['total']}</code>")

def fmt_final(stats, elapsed, un, stopped=False, sid=None):
    return (f"<blockquote>{E.SUCCESS} <b>{'Stopped' if stopped else 'Final'}</b></blockquote>\n"
            f"{E.KEY} <b>Session</b> ↬ <code>{sid}</code>\n"
            f"{E.FIRE} <b>Charged</b> ↬ <code>{stats['charged']}</code>\n"
            f"{E.APPROVED} <b>Approved</b> ↬ <code>{stats['approved']}</code>\n"
            f"{E.ERROR} <b>Declined</b> ↬ <code>{stats['declined']}</code>\n"
            f"{E.WARNING} <b>Errors</b> ↬ <code>{stats['error']}</code>\n"
            f"{E.CLOCK} <b>Time</b> ↬ <code>{elapsed}s</code>")

def get_keyboard(stats, last_cc, last_status, sid):
    cm1 = primary(f"• {last_cc} •", cb='u8')
    status_btn = primary(f"• 𝙍𝙀𝙎𝙋𝙊𝙉𝙎𝙀 ➜ {last_status} •", cb='u8')
    cm_charged = success(f"• 𝘾𝙃𝘼𝙍𝙂𝙀𝘿 🔥 ➜ [ {stats.get('charged', 0)} ] •", cb='x')
    cm3 = success(f"• 𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅ ➜ [ {stats.get('approved', 0)} ] •", cb='x')
    cm4 = danger(f"• 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ❌ ➜ [ {stats.get('declined', 0)} ] •", cb='x')
    cm5 = primary(f"• 𝙏𝙊𝙏𝘼𝙇 👻 ➜ [ {stats.get('total', 0)} ] •", cb='x')
    cm_err = danger(f"• 𝙀𝙍𝙍𝙊𝙍 ⚠️ ➜ [ {stats.get('error', 0)} ] •", cb='x')
    stop_btn = danger(f"[ 𝙎𝙏𝙊𝙋 ]", cb=f'jchk_stop_{sid}')
    return InlineKeyboardMarkup([[cm1], [status_btn], [cm_charged], [cm3], [cm4], [cm5], [cm_err], [stop_btn]])



async def jchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    tier = get_user_current_tier(uid)
    if tier not in ["Root", "X", "Owner"] and not is_db_admin(uid): return
    
    if time.time() < get_jio_ban(uid) and uid != OWNER_ID:
        await update.message.reply_text(f"{E.LOCK} <b>24h Limit Reached.</b>", parse_mode="HTML")
        return
        
    jio_num = get_jio_number()
    if not jio_num:
        await update.message.reply_text(f"{E.WARNING} <b>Jio Checker is offline.</b>", parse_mode="HTML")
        return

    raw_txt = ""
    if update.message.reply_to_message:
        r = update.message.reply_to_message
        if r.document:
            f = await context.bot.get_file(r.document.file_id)
            raw_txt = (await f.download_as_bytearray()).decode('utf-8', errors='ignore')
        elif r.text: raw_txt = r.text
    elif context.args: raw_txt = " ".join(context.args)

    cards = list(set([f"{m.group(1)}|{m.group(2).zfill(2)}|{m.group(3)[-2:]}|{m.group(4)}" for m in re.finditer(r'(\d{13,19})[|/:\s]+(\d{1,2})[|/:\s]+(\d{2,4})[|/:\s]+(\d{3,4})', raw_txt)]))
    if not cards or len(cards) > 100: 
        await update.message.reply_text(f"{E.ERROR} <b>Invalid cards or >100.</b>", parse_mode="HTML")
        return

    asyncio.create_task(_run_jchk_task(update, context, cards, jio_num, uid, tier))

async def _run_jchk_task(update, context, cards, jio_num, uid, tier):
    bot = context.bot
    proxies = get_active_proxy_strings(OWNER_ID) or []
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No proxies available.", parse_mode="HTML")
        return

    sid = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
    stats = {"total": len(cards), "checked": 0, "charged": 0, "approved": 0, "declined": 0, "error": 0, "processed": 0}
    start_time, stop_ev = time.time(), asyncio.Event()
    JIO_CHK_SESSIONS[sid] = {"stopped": False, "stop_event": stop_ev, "user_id": uid}

    msg = await update.message.reply_text(text=fmt_prog(stats, sid), parse_mode="HTML", reply_markup=get_keyboard(stats, "NONE", "PENDING", sid))
    amounts = ["129", "155", "199", "219", "239", "299", "349", "499", "599", "719", "839"]
    last_cc, last_status = "NONE", "PENDING"

    for i, cc in enumerate(cards, 1):
        if stop_ev.is_set(): break
        if i > 1 and (i - 1) % NAP_EVERY == 0 and uid != OWNER_ID:
            try: await msg.edit_text(f"<blockquote>{E.CLOCK} <b>Nap Time (5m)...</b></blockquote>", parse_mode="HTML")
            except: pass
            for _ in range(NAP_DURATION):
                if stop_ev.is_set(): break
                await asyncio.sleep(1)
            if stop_ev.is_set(): break

        amt = random.choice(amounts)
        res = None
        parsed_card = {"cc": cc.split("|")[0], "mm": cc.split("|")[1], "yy": "20"+cc.split("|")[2], "cvv": cc.split("|")[3]}
        
        # Try up to 5 times with different proxies
        for attempt in range(1):
            try:
                p = random.choice(proxies)
                res = await asyncio.to_thread(run_jio, jio_num, parsed_card, float(amt), p)
                if res.get("status") == "declined" and "Dead Proxy" in res.get("response", ""):
                    if attempt < 4: continue
                break
            except Exception as e:
                res = {"status": "error", "response": f"Bot Error: {e}", "gate": "jio"}
                break
        
        stats["processed"] += 1
        last_cc, last_status = cc, res["status"].upper()

        if res["status"] == "charged": stats["charged"] += 1
        elif res["status"] == "approved": stats["approved"] += 1
        elif res["status"] == "declined": stats["declined"] += 1
        else: stats["error"] += 1

        if res["status"] in ["charged", "approved"]:
            try:
                # User DM (Full CC)
                await bot.send_message(chat_id=uid, text=f"<blockquote>{E.FIRE} <b>Hit Detected</b></blockquote>\n<code>{cc}</code>\nResponse: <code>{res['response']}</code>", parse_mode="HTML")
                
                # ═══ NO CC IN GROUP, ONLY REF (Last 2 digits) ═══
                group_text = (
                    f"<blockquote>{E.APPROVED} <b>JIO HIT ({res['status'].upper()})</b></blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.GATE} <b>Gateway</b> ↬ <i>Jio Payment[{amt}]</i>\n"
                    f"{E.RESPONSE} <b>Status</b> ↬ <code>{res['response']}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.USER} <b>Verified by</b> ↬ <a href='tg://user?id={uid}'>{update.effective_user.first_name}</a> [{tier}]\n"
                    f"🔐 <i>Auto-verified via {BOT_NAME}</i>"
                )
                await bot.send_message(chat_id=HIT_DETECTION_GROUP_ID, text=group_text, parse_mode="HTML")
            except: pass

        if i % 2 == 0 or i == len(cards):
            try: await msg.edit_text(text=fmt_prog(stats, sid), parse_mode="HTML", reply_markup=get_keyboard(stats, last_cc, last_status, sid))
            except: pass

    if len(cards) >= 100 and uid != OWNER_ID: set_jio_ban(uid, time.time() + BAN_DURATION)
    try: await msg.edit_text(text=fmt_final(stats, round(time.time() - start_time, 2), update.effective_user.first_name, stop_ev.is_set(), sid), parse_mode="HTML", reply_markup=None)
    except: pass
    JIO_CHK_SESSIONS.pop(sid, None)

async def jchk_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sid = q.data.split("_")[2]
    if sid in JIO_CHK_SESSIONS: JIO_CHK_SESSIONS[sid]["stop_event"].set()


async def setnum_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not context.args or not re.fullmatch(r"\d{10}", context.args[0]):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Usage:</b></blockquote>\n"
            f"<code>/setnum 9876543210</code>\n"
            f"<i>(Must be a valid 10 digit Jio number)</i>", 
            parse_mode="HTML")
        return
    num = context.args[0].strip()
    set_jio_number(num)
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>JIO NUMBER SET</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>Number:</b> <code>{num}</code>\n"
        f"{E.APPROVED} <b>Status:</b> Jio Checker is now Online.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>", 
        parse_mode="HTML")

async def rmvnum_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    old_num = get_jio_number()
    set_jio_number("")
    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>JIO NUMBER REMOVED</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USER} <b>Removed:</b> <code>{old_num or 'None'}</code>\n"
        f"{E.WARNING} <b>Status:</b> Jio Checker is now Offline.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>", 
        parse_mode="HTML")

async def cknum_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    num = get_jio_number()
    if not num:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>NO NUMBER SET</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.WARNING} <b>Status:</b> Jio Checker is Offline.\n"
            f"<i>Use <code>/setnum</code> to add a number.</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>", 
            parse_mode="HTML")
    else:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>JIO NUMBER INFO</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.USER} <b>Active Number:</b> <code>{num}</code>\n"
            f"{E.APPROVED} <b>Status:</b> Online 🟢\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>", 
            parse_mode="HTML")

def register_jchk(app: Application):
    app.add_handler(CommandHandler("jchk", jchk_command))
    app.add_handler(CommandHandler("setnum", setnum_cmd))
    app.add_handler(CommandHandler("rmvnum", rmvnum_cmd))
    app.add_handler(CommandHandler("cknum", cknum_cmd))
    app.add_handler(CallbackQueryHandler(jchk_stop_callback, pattern=r"^jchk_stop_"))
    logger.info("✅ /jchk registered")
