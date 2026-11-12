import re, random, time, io, asyncio, logging
from datetime import datetime, timedelta
from bin import get_bin_info
from plans import get_user_current_tier
from database import get_user_credits, update_user_credits
from config import OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
last_command_time = {}


def luhn(cn):
    d = [int(x) for x in cn]
    for i in range(len(d)-2, -1, -2):
        d[i] *= 2
        if d[i] > 9: d[i] = (d[i]//10) + (d[i]%10)
    return sum(d) % 10 == 0


def gen_luhn(prefix, length=16):
    c = prefix
    while len(c) < length-1: c += str(random.randint(0, 9))
    for i in range(10):
        if luhn(c + str(i)): return c + str(i)
    return c + "0"


def parse_input(s):
    bin_p, mm, yy, amt, cvv = "", "rnd", "rnd", 10, "rnd"
    if "|" in s:
        parts = s.split("|")
        if parts: bin_p = parts[0].strip()
        if len(parts) > 1: mm = parts[1].strip() or "rnd"
        if len(parts) > 2:
            yy = parts[2].strip()
            if yy.lower() == "rnd": yy = "rnd"
            elif len(yy) == 4: yy = yy[2:]
        if len(parts) > 3:
            p4 = parts[3].strip()
            if p4.lower() == "rnd": cvv = "rnd"
            else:
                try:
                    ta = int(p4)
                    if ta > 0: amt = ta
                    else: cvv = p4
                except: cvv = p4
        if len(parts) > 4:
            try:
                ta = int(parts[4].strip())
                if ta > 0: amt = ta
            except: pass
    else:
        parts = s.split()
        if parts: bin_p = parts[0].strip()
        if len(parts) > 1:
            try:
                ta = int(parts[1].strip())
                if ta > 0: amt = ta
                else: mm = parts[1].strip()
            except: mm = parts[1].strip()
    if not bin_p or len(bin_p) < 6: raise ValueError("BIN ≥6 digits")
    return bin_p, mm, yy, amt, cvv


async def gen_cards(bin_p, mm, yy, amt, cvv):
    info = await get_bin_info(bin_p[:6])
    is_amex = info.get("scheme", "").lower() == "american express" or bin_p.startswith(("34", "37"))
    cards = []
    for _ in range(amt):
        cm = str(random.randint(1, 12)).zfill(2) if mm.lower() == "rnd" else mm
        if yy.lower() == "rnd":
            cur = time.strftime("%y"); cy = str(random.randint(int(cur), int(cur)+7)).zfill(2)
        else: cy = yy
        clen = 15 if is_amex else 16
        cn = gen_luhn(bin_p, clen)
        if cvv.lower() == "rnd":
            cc = str(random.randint(1000, 9999)) if is_amex else str(random.randint(100, 999))
        else:
            cc = cvv
            if is_amex and len(cc) == 3: cc += str(random.randint(0, 9))
            elif not is_amex and len(cc) == 4: cc = cc[:3]
        cards.append(f"{cn}|{cm}|{cy}|{cc}")
    return cards, info


def fmt_cards(cards, info):
    b = (info.get("scheme") or "N/A").title(); bk = info.get("bank") or "N/A"
    co = info.get("country") or "Unknown"; ct = info.get("type", "N/A")
    disp = cards[:50]
    cl = "\n".join(f"<code>{c}</code>" for c in disp)
    if len(cards) > 50: cl += f"\n\n<code>... +{len(cards)-50} more (in file)</code>"
    return (f"<blockquote>{E.SUCCESS} <b>{len(cards)} Cards</b></blockquote>\n\n{cl}\n\n"
            f"<blockquote><b>𝑩𝒊𝒏</b> ↬ {b}\n<b>𝑩𝒂𝒏𝒌</b> ↬ {bk}\n"
            f"<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ {co}\n<b>𝑻𝒚𝒑𝒆</b> ↬ {ct}</blockquote>")


async def process_gen(uid, bin_p, mm, yy, amt, cvv, update, context):
    try:
        c = get_user_credits(uid); unlim = c == float('inf')
        if amt > 10:
            prog = await update.message.reply_text(
                f"<blockquote>⏳ <b>Generating...</b></blockquote>\n"
                f"<code>{amt}</code> cards\n<code>{bin_p[:6]}</code>", parse_mode="HTML")
            cards, info = await gen_cards(bin_p, mm, yy, amt, cvv)
            buf = io.BytesIO("\n".join(cards).encode())
            buf.name = f"SPITZX_{bin_p[:6]}.txt"
            b = (info.get("scheme") or "N/A").title()
            bk = info.get("bank") or "N/A"
            await context.bot.send_document(chat_id=update.effective_chat.id, document=buf,
                caption=f"<blockquote>{E.SUCCESS} <b>{amt} Cards</b></blockquote>\n"
                        f"<b>BIN</b> ↬ <code>{bin_p[:6]}</code>\n"
                        f"<b>Brand</b> ↬ {b}\n<b>Bank</b> ↬ {bk}",
                parse_mode="HTML")
            try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prog.message_id)
            except: pass
        else:
            cards, info = await gen_cards(bin_p, mm, yy, amt, cvv)
            await update.message.reply_text(fmt_cards(cards, info), parse_mode="HTML")
        if not unlim:
            update_user_credits(uid, -1)
    except Exception as e:
        logger.error(f"gen: {e}")
        try: await update.message.reply_text(f"{E.ERROR} {e}", parse_mode="HTML")
        except: pass


async def handle_gen_command(update, context):
    uid = update.effective_user.id
    tier = get_user_current_tier(uid); now = datetime.now()
    if tier == "Trial" and uid in last_command_time:
        d = now - last_command_time[uid]
        if d < timedelta(seconds=10):
            await update.message.reply_text(f"⏳ Wait {10-int(d.total_seconds())}s.", parse_mode="HTML"); return
    last_command_time[uid] = now
    s = " ".join(context.args)
    if not s:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Generator</b></blockquote>\n"
            f"<code>/gen 486732</code>\n"
            f"<code>/gen 486732|rnd|rnd|rnd</code>", parse_mode="HTML"); return
    try: bin_p, mm, yy, amt, cvv = parse_input(s)
    except ValueError as e:
        await update.message.reply_text(f"{E.ERROR} {e}", parse_mode="HTML"); return
    asyncio.create_task(process_gen(uid, bin_p, mm, yy, amt, cvv, update, context))