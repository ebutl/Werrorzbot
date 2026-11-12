import re, random, time, logging, asyncio, html
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME, BOT_NAME, HIT_DETECTION_GROUP_ID
from database import get_active_proxy_strings, has_user_active_plan, is_db_admin
from emojis import PremiumEmoji as E
from jio_core import run_jio

logger = logging.getLogger(__name__)
_last_jhit_time = {}

ALLOWED_AMOUNTS = {"19", "29", "49", "69", "98", "129", "155", "199", "219", "239", "299", "349", "399", "449", "499", "599", "719", "839", "999", "1499"}
EMOJI_CHARGED = "5427168083074628963"

def _has_access(uid: int) -> bool:
    if uid == OWNER_ID or is_db_admin(uid): return True
    try: return has_user_active_plan(uid)
    except: return False

def _build_text(state: dict, is_working: bool) -> str:
    total = state["total"]
    checked = state["checked"]
    amount = state["amount"]
    results = state["results"]
    elapsed = state["elapsed"]

    has_paid = any(r["status"] in ["charged", "approved"] for r in results)

    if has_paid:
        status_text = f'Pᴀɪᴅ <tg-emoji emoji-id="{EMOJI_CHARGED}">✅</tg-emoji>'
    elif is_working:
        status_text = 'Hɪᴛᴛɪɴɢ…<tg-emoji emoji-id="6154603635981423575">⏳</tg-emoji>'
    else:
        status_text = 'Nᴏᴛ Pᴀɪᴅ <tg-emoji emoji-id="5273914604752216432">❌</tg-emoji>'

    text = (
        f"<blockquote>{E.FIRE} <b>JIO HITTER</b> {E.SPARKLE}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.THUNDER} <b>Hitter</b> ↬ Jio\n"
        f"{E.CARD} <b>Amount</b> ↬ <code>{amount} INR</code>\n"
        f"{E.STATS} <b>Progress</b> ↬ <code>{checked}/{total}</code>\n"
    )

    if not is_working:
        text += f"{E.THUNDER} <b>Status</b> ↬ {status_text}\n"

    if elapsed:
        text += f"{E.CLOCK} <b>Time</b> ↬ <code>{elapsed}s</code>\n"
    
    text += "━━━━━━━━━━━━━━━━━━"

    if is_working and not results:
        text += "\n<i>Starting...</i>"
    else:
        for r in results:
            text += f"\n<code>{r['cc']}</code>\n<b>{html.escape(r['response'])}</b>\n━━━━━━━━━━━━━━━━━━"

    if not is_working:
        text += f"\n{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"

    return text

async def jhit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    
    if not _has_access(uid):
        await update.message.reply_text(f"<blockquote>{E.LOCK} <b>Access Denied</b></blockquote>\n<i>Jio Hitter is for premium users only.</i>", parse_mode="HTML")
        return
        
    now = time.time()
    if now - _last_jhit_time.get(uid, 0) < 30 and uid != OWNER_ID:
        remaining = int(30 - (now - _last_jhit_time.get(uid, 0)))
        await update.message.reply_text(f"⏳ <b>Wait {remaining}s before next check.</b>", parse_mode="HTML")
        return

    parts = (update.message.text or "").split()
    if len(parts) < 3:
        await update.message.reply_text(f"<blockquote>{E.FIRE} <b>Usage</b></blockquote>\n<code>/jhit NUMBER AMOUNT CARD</code>", parse_mode="HTML")
        return
        
    number = parts[1].strip()
    amount = parts[2].strip()
    raw_cards = parts[3:]

    if update.message.reply_to_message and update.message.reply_to_message.text:
        raw_cards.extend(update.message.reply_to_message.text.split('\n'))
        
    if not re.fullmatch(r"\d{10}", number):
        await update.message.reply_text(f"{E.ERROR} <b>Invalid number.</b> Must be 10 digits.", parse_mode="HTML")
        return
        
    if amount not in ALLOWED_AMOUNTS:
        await update.message.reply_text(f"{E.ERROR} <b>Invalid amount.</b>", parse_mode="HTML")
        return
        
    cards = list(set([f"{m.group(1)}|{m.group(2).zfill(2)}|{m.group(3)[-2:]}|{m.group(4)}" for m in re.finditer(r'(\d{13,19})[|/:\s]+(\d{1,2})[|/:\s]+(\d{2,4})[|/:\s]+(\d{3,4})', " ".join(raw_cards))]))
    
    if not cards or len(cards) > 10:
        await update.message.reply_text(f"{E.ERROR} <b>Invalid cards or >10.</b>", parse_mode="HTML")
        return
        
    _last_jhit_time[uid] = now
    asyncio.create_task(_run_jhit(update, context, number, amount, cards, user.first_name, uid))

async def _run_jhit(update, context, number, amount, cards, user_name, uid):
    bot = context.bot
    proxies = get_active_proxy_strings(OWNER_ID) or []
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No proxies available.", parse_mode="HTML")
        return

    state = {"total": len(cards), "checked": 0, "amount": amount, "results": [], "elapsed": 0}
    msg = await update.message.reply_text(_build_text(state, True), parse_mode="HTML")
    start_time = time.time()

    for cc in cards:
        parsed_card = {"cc": cc.split("|")[0], "mm": cc.split("|")[1], "yy": "20"+cc.split("|")[2], "cvv": cc.split("|")[3]}
        res = None
        
        # Try 2 times with different proxies if proxy drops connection
        for attempt in range(1):
            try:
                p = random.choice(proxies)
                res = await asyncio.to_thread(run_jio, number, parsed_card, float(amount), p)
                
                # If proxy is dead, retry with a new one
                if res.get("status") == "declined" and "Connection Dropped" in res.get("response", ""):
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                break
            except Exception as e:
                res = {"status": "error", "response": f"Bot Error: {e}", "gate": "jio"}
                break
                
        state["checked"] += 1
        state["results"].append({"cc": cc, "status": res.get("status", "error"), "response": res.get("response", "Unknown")})
        state["elapsed"] = round(time.time() - start_time, 2)

        try: await msg.edit_text(_build_text(state, True), parse_mode="HTML")
        except: pass

        # Hit group logic (Masked ref only)
        if res.get("status") in ["charged", "approved"]:
            try:
                group_text = (
                    f"<blockquote>{E.APPROVED} <b>JIO HIT ({res['status'].upper()})</b></blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.GATE} <b>Gateway</b> ↬ <i>Jio Payment[{amount}]</i>\n"
                    f"{E.RESPONSE} <b>Status</b> ↬ <code>{res['response']}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.USER} <b>Verified by</b> ↬ <a href='tg://user?id={uid}'>{user_name}</a>\n"
                    f"🔐 <i>Auto-verified via {BOT_NAME}</i>"
                )
                await bot.send_message(chat_id=HIT_DETECTION_GROUP_ID, text=group_text, parse_mode="HTML")
            except: pass

        if len(cards) > 1: await asyncio.sleep(2)

    state["elapsed"] = round(time.time() - start_time, 2)
    try: await msg.edit_text(_build_text(state, False), parse_mode="HTML")
    except: pass

def register_jio(app: Application):
    app.add_handler(CommandHandler("jhit", jhit_command))
