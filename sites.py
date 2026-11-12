"""sites.py — Owner-only global sites (one-shot + retry on error/unknown)."""

import re, io, asyncio, aiohttp, random, logging, time
from datetime import datetime

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, Application

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E
from ui import primary, success, danger
from database import (
    add_site, site_exists, get_all_sites, get_all_working_sites,
    delete_site, delete_all_sites, get_total_sites,
    get_user_active_proxies, get_user_proxies_new,
)
from api_config import get_api_endpoint
from api_parse import get_gateway, get_price_currency

logger = logging.getLogger(__name__)

TEST_CARD = "4910149950579116|03|28|106"
TIMEOUT = 20
MAX_CONCURRENT = 10
SITE_DELAY = 0.1
SITE_MAX_RETRIES = 1   # 1 retry on error/unknown

DEAD_GATEWAYS = [
    "Authorize.net", "AuthorizeNet", "authorize.net", "authorizenet",
    "Stripe", "stripe", "Stripe.com",
]

VALID_RESPONSES = [
    "CARD_DECLINED", "INSUFFICIENT_FUNDS", "INVALID_CVC",
    "3D_AUTHENTICATION", "ORDER_PAID", "ORDER_PLACED", "APPROVED", "DECLINED",
    "INSUFFICIENT FUNDS", "INVALID CVC", "3DS_REQUIRED", "3D SECURE",
    "DO NOT HONOR", "EXPIRED",
]

PENDING_VALIDATIONS = {}

def is_owner(uid): return uid == OWNER_ID

def is_dead_gateway(gw):
    if not gw: return False
    gl = gw.lower()
    return any(d.lower() in gl for d in DEAD_GATEWAYS)


def is_shopify_gateway(gw):
    """Accept ONLY Shopify-family gateways.
    Rejects Authorize.net, Payplug, Oceanpayment, Stripe Card Payments,
    Creditcard, and any other non-Shopify gateway.
    Also rejects 'N/A' / empty / None (unknown gateway)."""
    if not gw:
        return False
    gl = str(gw).strip().lower()
    if not gl or gl == "n/a":
        return False
    return "shopify" in gl

def clean_url(url):
    url = url.strip()
    if not url: return None
    if not url.startswith(("http://", "https://")): url = "https://" + url
    if url.startswith("http://"): url = url.replace("http://", "https://", 1)
    if url.endswith("/"): url = url[:-1]
    return url


def is_valid_site_url(url):
    """STRICT URL validation — reject proxies and malformed strings.
    Accepts: https://example.com, https://sub.example.com:443/path
    Rejects: https://host:port:user:pass  (proxy)
             user:pass@host:port         (proxy)
             1.2.3.4:8080                (bare proxy)
             host:port:user:pass         (proxy)
             non-http protocol, no dot, spaces, etc."""
    if not url:
        return False
    u = str(url).strip()

    if not u.startswith(("http://", "https://")):
        return False

    after_proto = u.split("://", 1)[1]

    # Host part = everything before first /, ?, #
    host_part = re.split(r'[/?#]', after_proto, 1)[0]

    if not host_part:
        return False

    # Reject basic-auth format: user:pass@host
    if "@" in host_part:
        return False

    # Reject proxy format: host:port:user:pass (3 colons) or any >1 colon
    if host_part.count(":") > 1:
        return False

    # Domain must have at least 1 dot
    domain = host_part.split(":")[0]
    if not domain or "." not in domain:
        return False

    # Reject spaces
    if " " in domain:
        return False

    # Reject pure numeric (not a valid domain)
    if re.match(r'^\d+$', domain):
        return False

    return True

def extract_urls_from_text(text):
    """Extract URLs. Rejects proxies: host:port:user:pass, user:pass@host:port, etc."""
    urls = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        for part in re.split(r'[,\s]+', line):
            part = part.strip()
            if not part or part.startswith("#"): continue

            # ═══ PROXY GUARD — reject BEFORE clean_url ═══
            stripped = re.sub(r'^(?:https?|socks[45])://', '', part)
            host_sec = re.split(r'[/?#]', stripped, 1)[0]
            if host_sec.count(":") >= 2 or "@" in host_sec:
                continue  # Skip proxy-like line

            url = clean_url(part)
            if url and is_valid_site_url(url) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls

async def verify_api():
    api_url = get_api_endpoint()
    if not api_url:
        return False, "No API configured"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(api_url) as r:
                if r.status >= 500:
                    return False, f"API HTTP {r.status}"
                return True, "OK"
    except asyncio.TimeoutError:
        return False, "API timeout"
    except Exception as e:
        return False, str(e)[:50]

async def _check_site_raw(site_url, proxy, card=TEST_CARD):
    api_url = get_api_endpoint()
    if not api_url:
        return {"error": "No API"}

    base = api_url.split("?")[0].rstrip("/")
    params = {"site": site_url, "cc": card, "proxy": proxy}

    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT, connect=TIMEOUT)
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(base, params=params) as resp:
                if resp.status >= 400:
                    return {"error": f"HTTP {resp.status}"}
                try:
                    data = await resp.json()
                except Exception:
                    return {"error": "Bad JSON"}
                if not data:
                    return {"error": "Empty"}

                status_raw = data.get("Status", data.get("status", False))
                status = bool(status_raw)
                if isinstance(status_raw, str):
                    status = status_raw.lower() in ("true", "1", "yes", "approved")

                response = str(data.get("Response", data.get("response", "")) or "")
                gateway = get_gateway(data)
                price_val, currency, sym, price_display = get_price_currency(data)

                return {"status": status, "response": response,
                        "gateway": gateway, "price": price_val,
                        "currency": currency, "price_display": price_display}
    except asyncio.TimeoutError:
        return {"error": f"Timeout {TIMEOUT}s"}
    except aiohttp.ClientError as e:
        return {"error": f"Net: {str(e)[:30]}"}
    except Exception as e:
        return {"error": str(e)[:40]}

async def check_site_with_retry(site_url, proxies, card=TEST_CARD, max_retries=SITE_MAX_RETRIES):
    """Retry on error/unknown with a different proxy each attempt."""
    last = None
    for attempt in range(max_retries + 1):
        proxy = random.choice(proxies) if proxies else ""
        r = await _check_site_raw(site_url, proxy, card)
        last = r
        if not r.get("error"):
            response = str(r.get("response", "")).upper()
            if any(k in response for k in VALID_RESPONSES):
                break
            if r.get("price", 0) > 0 or r.get("status") is True:
                break
        if attempt < max_retries:
            await asyncio.sleep(0.5)
    return last

def _decide(result, max_price):
    if result.get("error"):
        return False, "error", result.get("error", "?")[:60]

    gateway = result.get("gateway", "")
    price = result.get("price", 0)
    status = result.get("status", False)
    response = str(result.get("response", "")).upper()

    # ═══ STRICT SHOPIFY-ONLY: reject non-Shopify gateways ═══
    if not is_shopify_gateway(gateway):
        return False, "dead_gw", f"NON_SHOPIFY: {gateway or 'N/A'}"

    if gateway and gateway != "N/A" and is_dead_gateway(gateway):
        return False, "dead_gw", f"DEAD_GW: {gateway}"

    # ═══ NEW: Reject $0.00 / unknown price sites ═══
    if price is None or price <= 0:
        return False, "zero_price", f"Zero price: ${price if price else 0:.2f}"

    if price > max_price and price > 0:
        return False, "over_price", f"${price:.2f} > ${max_price}"

    if any(k in response for k in VALID_RESPONSES):
        return True, "by_response", f"RESP: {response[:25]} | ${price:.2f}"

    if price > 0:
        return True, "by_price", f"${price:.2f}"

    if status is True:
        return True, "by_status", "status=ok"

    return False, "dead", response[:60]



def _is_proxy_like(url):
    """BULLETPROOF proxy detection - works on string pattern, no regex exceptions.
    Detects: host:port:user:pass, user:pass@host, host:port:user:pass with prefix.
    Returns True if this looks like a proxy, False if looks like real site URL."""
    if not url:
        return True  # empty treated as invalid
    t = str(url).strip().lower()
    # Strip protocol prefix
    for proto in ("https://", "http://", "socks5://", "socks4://"):
        if t.startswith(proto):
            t = t[len(proto):]
            break
    # Strip path/query/fragment — take host part only
    for sep in ("/", "?", "#"):
        if sep in t:
            t = t.split(sep, 1)[0]
    # Reject basic-auth: user:pass@host
    if "@" in t:
        return True
    # Reject proxy format: host:port:user:pass has 3+ colons
    # host:port has 1 colon (allowed) — domain must have dot
    if t.count(":") > 1:
        return True
    # Extract domain (before any colon)
    domain = t.split(":")[0]
    # Domain must have a dot (rejects "localhost", "abc")
    if "." not in domain:
        return True
    # Domain must have at least one letter (rejects "1.2.3.4" but that's still IP)
    # Actually reject pure IP addresses too
    import re as _re
    if _re.match(r'^\d+\.\d+\.\d+\.\d+$', domain):
        return True  # pure IP, not a real shopify site
    # Domain can't have spaces or weird chars
    if " " in domain or "\t" in domain:
        return True
    return False


def _deny_text():
    return (f"<blockquote>{E.ERROR} <b>Owner Only</b></blockquote>\n\n"
            f"<i>Sites managed globally by owner.</i>")

async def _read_input(update, context):
    text = ""
    if update.message.reply_to_message:
        r = update.message.reply_to_message
        if r.document:
            fn = r.document.file_name or ""
            if fn.lower().endswith((".txt", ".csv", ".text")):
                f = await context.bot.get_file(r.document.file_id)
                c = await f.download_as_bytearray()
                text = c.decode('utf-8', errors='ignore')
        elif r.text:
            text = r.text
    elif update.message.document:
        fn = update.message.document.file_name or ""
        if fn.lower().endswith((".txt", ".csv", ".text")):
            f = await context.bot.get_file(update.message.document.file_id)
            c = await f.download_as_bytearray()
            text = c.decode('utf-8', errors='ignore')
    if context.args and not text:
        text = " ".join(context.args)
    return text

async def addsite_command(update, context):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return

    api_ok, api_detail = await verify_api()
    if not api_ok:
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>API Not Reachable</b></blockquote>\n\n"
            f"{E.NOTE} <b>Detail:</b> <code>{api_detail}</code>\n"
            f"{E.LINK} <b>API:</b> <code>{get_api_endpoint()[:60]}</code>\n\n"
            f"{E.INFO} <i>API dead hai — /capi URL se change karo pehle</i>",
            parse_mode="HTML")
        return

    text = await _read_input(update, context)
    if not text:
        await update.message.reply_text(
            f"<blockquote>{E.SITES} <b>Add Sites</b></blockquote>\n\n"
            f"<code>/addsite https://example.com</code>\n"
            f"<code>/addsite url1 url2</code>\n\n"
            f"<i>Or reply to .txt with URLs</i>",
            parse_mode="HTML")
        return

    urls = extract_urls_from_text(text)
    if not urls:
        await update.message.reply_text(f"{E.ERROR} No valid URLs.", parse_mode="HTML")
        return

    proxies = get_user_active_proxies(OWNER_ID)
    if not proxies:
        all_p = get_user_proxies_new(OWNER_ID)
        proxies = [p["proxy"] for p in all_p]
    if not proxies:
        await update.message.reply_text(
            f"<blockquote>{E.WARNING} <b>No Proxies</b></blockquote>\n\n"
            f"<code>/proxy host:port:user:pass</code>", parse_mode="HTML")
        return

    PENDING_VALIDATIONS[user.id] = urls

    kb = InlineKeyboardMarkup([
        [
            primary("0-5 USD", "addsite_price_5", icon="5895652322469482989"),
            primary("0-10 USD", "addsite_price_10", icon="5895652322469482989"),
        ],
        [
            success("0-20 USD", "addsite_price_20", icon="5895652322469482989"),
            success("0-40 USD", "addsite_price_40", icon="5895652322469482989"),
        ],
        [
            danger("Cancel", "addsite_cancel", icon="6043931300950184015"),
        ],
    ])

    await update.message.reply_text(
        f"<blockquote>{E.SITES} <b>Select Price Range</b> 💲</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.STATS} <b>Total Sites:</b> <code>{len(urls)}</code>\n"
        f"{E.INFO} <i>Retry on error/unknown (1 retry)</i>\n"
        f"{E.NOTE} <i>Accept if valid response OR price OR status</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML",
        reply_markup=kb)

async def addsite_price_callback(update, context):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if user_id != OWNER_ID:
        await q.answer("Owner only", show_alert=True)
        return

    data = q.data
    if data == "addsite_cancel":
        PENDING_VALIDATIONS.pop(user_id, None)
        try:
            await q.edit_message_text(
                f"<blockquote>{E.INFO} <b>Cancelled</b></blockquote>",
                parse_mode="HTML")
        except Exception: pass
        return

    max_price = 0
    for p in [5, 10, 20, 40]:
        if data == f"addsite_price_{p}":
            max_price = p
            break
    else:
        await q.answer("Invalid selection", show_alert=True)
        return

    if user_id not in PENDING_VALIDATIONS:
        await q.edit_message_text(
            f"{E.ERROR} Session expired. Run /addsite again.",
            parse_mode="HTML")
        return

    urls = PENDING_VALIDATIONS.pop(user_id)

    proxies = get_user_active_proxies(OWNER_ID)
    if not proxies:
        all_p = get_user_proxies_new(OWNER_ID)
        proxies = [p["proxy"] for p in all_p]
    if not proxies:
        await q.edit_message_text(f"{E.ERROR} No proxies.", parse_mode="HTML")
        return

    eta_sec = max(1, len(urls) // MAX_CONCURRENT * (TIMEOUT // 4))
    eta_str = f"{eta_sec // 60}m {eta_sec % 60}s" if eta_sec > 60 else f"{eta_sec}s"

    try:
        status_message = await q.edit_message_text(
            f"<blockquote>{E.FLY} <b>Checking {len(urls)} sites...</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.INFO} <b>Range:</b> <code>$0 - ${max_price}</code>\n"
            f"{E.GLOBE} <b>Proxies:</b> <code>{len(proxies)}</code>\n"
            f"{E.CLOCK} <b>ETA:</b> <code>~{eta_str}</code>\n"
            f"{E.NOTE} <i>Timeout: {TIMEOUT}s | Concurrency: {MAX_CONCURRENT} | 1 retry</i>\n"
            f"<code>0/{len(urls)}</code>",
            parse_mode="HTML")
    except Exception:
        status_message = await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=f"Processing {len(urls)} sites...", parse_mode="HTML")

    asyncio.create_task(_run_add(
        urls, proxies, status_message, q.message.chat_id,
        max_price, context, eta_str))

async def _run_add(urls, proxies, prog, chat_id, max_price, context, eta_str):
    # ═══ LAYER 2: PROXY GUARD — filter BEFORE any processing ═══
    _orig_count = len(urls)
    urls = [u for u in urls if not _is_proxy_like(u)]
    if len(urls) < _orig_count:
        print(f"[addsite] Dropped {_orig_count - len(urls)} proxy-like URLs")
    if not urls:
        try:
            await context.bot.send_message(chat_id=chat_id,
                text=f"<blockquote>⚠️ <b>All URLs rejected</b></blockquote>\n"
                     f"<i>{_orig_count} proxy-like URLs — no valid sites</i>",
                parse_mode="HTML")
        except: pass
        try: await prog.delete()
        except: pass
        return
    total = len(urls)
    checked = added = rejected = duplicates = 0
    added_by_response = added_by_price = added_by_status = 0
    over_price = dead_gw = errors = 0
    results = []
    sample_errors = []
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start_t = time.time()
    last_edit = 0

    async def check_one(url):
        nonlocal checked, added, rejected, duplicates
        nonlocal added_by_response, added_by_price, added_by_status
        nonlocal over_price, dead_gw, errors

        # ═══ LAYER 4: PROXY GUARD in check_one ═══
        if _is_proxy_like(url):
            return {"url": url, "status": "Rejected", "gateway": "",
                    "price": 0, "price_display": "$0",
                    "category": "proxy", "detail": "PROXY_NOT_SITE"}

        if site_exists(url):
            duplicates += 1
            return {"url": url, "status": "Duplicate", "gateway": "",
                    "price": 0, "price_display": "$0",
                    "category": "dupe", "detail": ""}

        try:
            raw = await check_site_with_retry(url, proxies)
        except Exception as e:
            errors += 1; rejected += 1
            return {"url": url, "status": "Error", "error": str(e)[:50],
                    "gateway": "", "price": 0, "price_display": "$0",
                    "category": "error", "detail": str(e)[:50]}

        is_working, category, detail = _decide(raw, max_price)

        price_display = raw.get("price_display") or f"${raw.get('price', 0):.2f}"

        if is_working:
            add_site(url, raw.get("gateway", "") or "", raw.get("price", 0),
                     "Working", OWNER_ID)
            added += 1
            if category == "by_response": added_by_response += 1
            elif category == "by_price": added_by_price += 1
            else: added_by_status += 1
            return {"url": url, "status": "Working",
                    "gateway": raw.get("gateway", ""),
                    "price": raw.get("price", 0),
                    "price_display": price_display,
                    "response": raw.get("response", ""),
                    "category": category, "detail": detail}

        rejected += 1
        if category == "over_price": over_price += 1
        elif category == "dead_gw": dead_gw += 1
        elif category == "error": errors += 1
        else:
            if len(sample_errors) < 5:
                sample_errors.append(f"{url[:30]}: {detail[:40]}")

        return {"url": url, "status": "Rejected",
                "gateway": raw.get("gateway", ""),
                "price": raw.get("price", 0),
                "price_display": price_display,
                "error": detail, "category": category, "detail": detail}

    async def worker(url):
        nonlocal checked, last_edit
        async with sem:
            await asyncio.sleep(SITE_DELAY)
            r = await check_one(url)
            checked += 1
            results.append(r)
            now = time.time()
            if (now - last_edit >= 3) or (checked == total):
                last_edit = now
                el = now - start_t
                rate = checked / el if el > 0 else 0
                remaining = (total - checked) / rate if rate > 0 else 0
                eta = f"{int(remaining // 60)}m {int(remaining % 60)}s" if remaining > 60 else f"{int(remaining)}s"
                try:
                    await prog.edit_text(
                        f"<blockquote>{E.FLY} <b>Checking...</b></blockquote>\n"
                        f"<code>{checked}/{total}</code>\n"
                        f"<b>Range:</b> <code>$0 - ${max_price}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{E.SUCCESS} Added: <code>{added}</code>\n"
                        f"  ↳ By Resp: <code>{added_by_response}</code>\n"
                        f"  ↳ By Price: <code>{added_by_price}</code>\n"
                        f"  ↳ By Status: <code>{added_by_status}</code>\n"
                        f"{E.ERROR} Rejected: <code>{rejected}</code>\n"
                        f"  ↳ Over ${max_price}: <code>{over_price}</code>\n"
                        f"  ↳ Dead: <code>{rejected - over_price - dead_gw - errors}</code>\n"
                        f"{E.WARNING} Dupes: <code>{duplicates}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{E.CLOCK} Rate: <code>{rate:.1f}/s</code> | ETA: <code>{eta}</code>",
                        parse_mode="HTML")
                except Exception: pass

    await asyncio.gather(*[worker(u) for u in urls])

    elapsed = time.time() - start_t
    fc = f"SITE SCAN REPORT\n{'=' * 60}\n"
    fc += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    fc += f"API: {get_api_endpoint()}\n"
    fc += f"Price Range: $0 - ${max_price}\n"
    fc += f"Mode: RETRY ({SITE_MAX_RETRIES} retries)\n"
    fc += f"Timeout: {TIMEOUT}s | Concurrency: {MAX_CONCURRENT}\n"
    fc += f"{'-' * 60}\n"
    fc += f"Total: {total}\n"
    fc += f"Added: {added}  (by_resp={added_by_response}, by_price={added_by_price}, by_status={added_by_status})\n"
    fc += f"Rejected: {rejected}\n"
    fc += f"  - Over ${max_price}: {over_price}\n"
    fc += f"  - Dead GW: {dead_gw}\n"
    fc += f"  - Errors: {errors}\n"
    fc += f"Dupes: {duplicates}\n"
    fc += f"Time: {int(elapsed)}s\n"
    fc += "=" * 60 + "\n\n"
    fc += "SITE | PRICE | GATEWAY | DETAIL | STATUS | CATEGORY\n"
    fc += "-" * 60 + "\n"
    for r in results:
        p = r.get('price_display') or (f"${r['price']:.2f}" if r.get('price') else "$0")
        detail = (r.get('detail') or r.get('error', '') or '')[:35]
        gw = r.get('gateway', '') or 'N/A'
        fc += f"{r['url']} | {p} | {gw} | {detail} | {r['status']} | {r.get('category', '')}\n"

    if sample_errors:
        fc += "\n\nSAMPLE REJECTIONS:\n" + "-" * 60 + "\n"
        for e in sample_errors:
            fc += e + "\n"

    buf = io.BytesIO(fc.encode('utf-8'))
    buf.name = f"site_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    caption = (
        f"<blockquote>{E.REPORT} <b>Scan Complete</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Range:</b> <code>$0 - ${max_price}</code>\n"
        f"{E.SUCCESS} Added: <code>{added}</code>\n"
        f"   ↳ By Resp: <code>{added_by_response}</code>\n"
        f"   ↳ By Price: <code>{added_by_price}</code>\n"
        f"{E.ERROR} Rejected: <code>{rejected}</code>\n"
        f"   ↳ Over: <code>{over_price}</code>\n"
        f"{E.WARNING} Dupes: <code>{duplicates}</code>\n"
        f"{E.CLOCK} Time: <code>{int(elapsed)}s</code>\n\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")

    try:
        await context.bot.send_document(chat_id=chat_id, document=buf,
                                         caption=caption, parse_mode="HTML")
    except Exception:
        try:
            await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")
        except Exception: pass
    buf.close()
    try: await prog.delete()
    except Exception: pass

async def testsite_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML"); return

    # ═══ AUTO-CLEANUP: delete invalid/proxy-like entries first ═══
    all_raw = get_all_sites()
    cleaned = 0
    for sd in all_raw:
        if not is_valid_site_url(sd['url']):
            delete_site(sd['url'])
            cleaned += 1
    if cleaned:
        try:
            await update.message.reply_text(
                f"<blockquote>{E.WARNING} <b>Cleanup</b></blockquote>\n"
                f"{E.CLOSE} Removed <code>{cleaned}</code> invalid/proxy entries",
                parse_mode="HTML")
        except: pass

    sites = get_all_sites()
    if not sites:
        await update.message.reply_text(f"{E.INFO} No sites.", parse_mode="HTML"); return
    proxies = get_user_active_proxies(OWNER_ID) or [p["proxy"] for p in get_user_proxies_new(OWNER_ID)]
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No proxies.", parse_mode="HTML"); return

    prog = await update.message.reply_text(
        f"<blockquote>{E.FLY} <b>Testing {len(sites)} sites...</b></blockquote>\n"
        f"<code>0/{len(sites)}</code>", parse_mode="HTML")
    asyncio.create_task(_run_ts(sites, proxies, prog, update, context))

async def _run_ts(sites, proxies, prog, update, context):
    # ═══ LAYER 3: PROXY GUARD — delete proxy URLs from DB first ═══
    _cleaned = 0
    for sd in list(sites):
        if _is_proxy_like(sd.get("url", "")):
            try:
                delete_site(sd["url"])
                _cleaned += 1
            except: pass
    if _cleaned:
        sites = [sd for sd in sites if not _is_proxy_like(sd.get("url", ""))]
        try:
            await update.message.reply_text(
                f"<blockquote>🗑️ <b>Auto-Cleanup</b></blockquote>\n"
                f"<i>Deleted {_cleaned} proxy URLs from DB</i>",
                parse_mode="HTML")
        except: pass
    if not sites:
        try:
            await prog.edit_text(f"{E.INFO} <b>No valid sites</b>", parse_mode="HTML")
        except: pass
        return
    total = len(sites)
    checked = working = dead = dead_gw = deleted = 0
    results = []
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start = time.time()
    last_edit = 0

    async def check_one(sd):
        nonlocal checked, working, dead, dead_gw, deleted
        url = sd["url"]
        try:
            raw = await check_site_with_retry(url, proxies)
        except Exception:
            dead += 1; delete_site(url); deleted += 1
            return {"url": url, "status": "Error", "gateway": "",
                    "price": 0, "price_display": "$0"}

        price_display = raw.get("price_display") or f"${raw.get('price', 0):.2f}"

        if raw.get("error"):
            dead += 1; delete_site(url); deleted += 1
            return {"url": url, "status": "Error",
                    "gateway": raw.get("gateway", ""),
                    "price": 0, "price_display": price_display,
                    "error": raw.get("error")}

        gateway = raw.get("gateway", "")
        price = raw.get("price", 0)
        status = raw.get("status", False)
        response = str(raw.get("response", "")).upper()

        # ═══ STRICT SHOPIFY-ONLY: delete non-Shopify sites ═══
        if not is_shopify_gateway(gateway):
            dead_gw += 1; dead += 1; delete_site(url); deleted += 1
            return {"url": url, "status": "Dead GW", "gateway": gateway,
                    "price": price, "price_display": price_display}

        if gateway and gateway != "N/A" and is_dead_gateway(gateway):
            dead_gw += 1; dead += 1; delete_site(url); deleted += 1
            return {"url": url, "status": "Dead GW", "gateway": gateway,
                    "price": price, "price_display": price_display}

        is_valid = any(k in response for k in VALID_RESPONSES)
        if is_valid or (price > 0 and price <= 40) or status is True:
            working += 1
            return {"url": url, "status": "Working", "gateway": gateway,
                    "price": price, "price_display": price_display}

        dead += 1; delete_site(url); deleted += 1
        return {"url": url, "status": "Dead", "gateway": gateway,
                "price": price, "price_display": price_display,
                "error": raw.get("response", "?")[:40]}

    async def worker(sd):
        nonlocal checked, last_edit
        async with sem:
            await asyncio.sleep(SITE_DELAY)
            r = await check_one(sd)
            checked += 1
            results.append(r)
            now = time.time()
            if (now - last_edit >= 3) or (checked == total):
                last_edit = now
                try:
                    await prog.edit_text(
                        f"<blockquote>{E.FLY} <b>Testing...</b></blockquote>\n"
                        f"<code>{checked}/{total}</code>\n"
                        f"{E.SUCCESS} Working: <code>{working}</code>\n"
                        f"{E.ERROR} Dead: <code>{dead}</code>\n"
                        f"{E.CLOSE} Deleted: <code>{deleted}</code>",
                        parse_mode="HTML")
                except Exception: pass

    await asyncio.gather(*[worker(s) for s in sites])

    el = time.time() - start
    fc = f"SITE TEST REPORT\n{'=' * 60}\n"
    fc += f"Total: {total}\nWorking: {working}\nDead: {dead}\n"
    fc += f"Dead GW: {dead_gw}\nDeleted: {deleted}\nTime: {int(el)}s\n"
    fc += "=" * 60 + "\n\nSITE | GATEWAY | PRICE | STATUS\n" + "-" * 60 + "\n"
    for r in results:
        p = r.get('price_display') or (f"${r['price']:.2f}" if r.get('price') else "$0")
        gw = r.get('gateway') or 'N/A'
        st = "WORKING" if r["status"] == "Working" else "DELETED"
        fc += f"{r['url']} | {gw} | {p} | {st}\n"

    buf = io.BytesIO(fc.encode('utf-8'))
    buf.name = f"site_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    try:
        await update.message.reply_document(
            document=buf,
            caption=(f"<blockquote>{E.REPORT} <b>Complete</b></blockquote>\n"
                     f"{E.SUCCESS} Working: <code>{working}</code>\n"
                     f"{E.ERROR} Deleted: <code>{deleted}</code>\n"
                     f"{E.CLOCK} Time: <code>{int(el)}s</code>"),
            parse_mode="HTML")
    except Exception:
        await update.message.reply_text(
            f"Working: {working}, Deleted: {deleted}", parse_mode="HTML")
    buf.close()
    try: await prog.delete()
    except Exception: pass

async def getsite_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML"); return
    kb = InlineKeyboardMarkup([
        [success("Clean", "getsite_clean"), primary("Detailed", "getsite_detailed")],
        [danger("Cancel", "getsite_cancel")]])
    await update.message.reply_text(
        f"<blockquote>{E.SITES} <b>Export Sites</b></blockquote>",
        parse_mode="HTML", reply_markup=kb)

async def getsite_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not is_owner(q.from_user.id):
        await q.answer("Owner only", show_alert=True); return
    if q.data == "getsite_cancel":
        await q.edit_message_text(f"{E.INFO} Cancelled.", parse_mode="HTML"); return
    sites = get_all_sites()
    if not sites:
        await q.edit_message_text(f"{E.INFO} No sites.", parse_mode="HTML"); return
    working = get_all_working_sites()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    if q.data == "getsite_clean":
        content = "\n".join(f"{s['url']} | ${s['price']:.2f}" if s.get('price') else f"{s['url']} | N/A" for s in sites)
        fname = f"urls_{ts}.txt"
    else:
        content = "SITE | GATEWAY | PRICE | STATUS\n" + "-" * 60 + "\n"
        for s in sites:
            p = f"${s['price']:.2f}" if s.get('price') else "N/A"
            content += f"{s['url']} | {s.get('gateway', '') or 'N/A'} | {p} | {s.get('status', '')}\n"
        fname = f"sites_{ts}.txt"

    file = io.BytesIO(content.encode('utf-8'))
    file.name = fname
    await q.edit_message_text("⏳ Generating...")
    await context.bot.send_document(
        chat_id=q.message.chat_id, document=file,
        caption=f"<b>Sites:</b> {len(sites)} | <b>Working:</b> {len(working)}\n"
                f"<i>File includes prices and full details.</i>",
        parse_mode="HTML")
    file.close()
    try: await q.delete_message()
    except Exception: pass

async def rmsite_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML"); return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/rmsite URL</code>", parse_mode="HTML"); return
    url = clean_url(context.args[0])
    if not url or not site_exists(url):
        await update.message.reply_text(f"{E.ERROR} Not found.", parse_mode="HTML"); return
    delete_site(url)
    await update.message.reply_text(
        f"{E.SUCCESS} Deleted. Remaining: {get_total_sites()}", parse_mode="HTML")

async def clearsites_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML"); return
    sites = get_all_sites()
    if not sites:
        await update.message.reply_text(f"{E.INFO} No sites.", parse_mode="HTML"); return
    n = delete_all_sites()
    await update.message.reply_text(f"{E.SUCCESS} All {n} sites deleted.", parse_mode="HTML")

def register_sites(app: Application):
    app.add_handler(CommandHandler("addsite", addsite_command))
    app.add_handler(CommandHandler("ts", testsite_command))
    app.add_handler(CommandHandler("getsite", getsite_command))
    app.add_handler(CommandHandler("rmsite", rmsite_command))
    app.add_handler(CommandHandler("clearsites", clearsites_command))
    app.add_handler(CallbackQueryHandler(getsite_callback, pattern=r"^getsite_"))
    app.add_handler(CallbackQueryHandler(addsite_price_callback, pattern=r"^addsite_"))
    logger.info("✅ /sites registered")