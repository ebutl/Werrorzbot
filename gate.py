"""gate.py — Site scanner"""
import re, asyncio, aiohttp, logging
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, Set
from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
RATE = 3
CACHE = 300
MAX_CONC = 10

CMS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js',
    'BigCommerce': r'cdn\.bigcommerce\.com',
    'Wix': r'static\.parastorage\.com',
    'Squarespace': r'static1\.squarespace\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/',
    'Magento': r'static/version\d+/frontend/',
    'PrestaShop': r'prestashop\.js',
    'OpenCart': r'catalog/view/theme',
    'WordPress': r'wp-content|wp-includes/',
}

PAY = ["PayPal", "Stripe", "Braintree", "Square", "Cybersource", "Authorize.Net",
       "2Checkout", "Adyen", "Worldpay", "SagePay", "Razorpay", "Apple Pay",
       "Google Pay", "Skrill", "PayU", "CCAvenue", "Klarna", "Affirm", "Afterpay",
       "BitPay", "Coinbase Commerce", "Paytm", "UPI"]

user_last: Dict[int, datetime] = {}
cache: Dict[str, Dict] = {}
concurrent: Set[str] = set()
sem = asyncio.Semaphore(MAX_CONC)
_session = None


async def _init_s():
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=30)
        _session = aiohttp.ClientSession(timeout=timeout,
            connector=aiohttp.TCPConnector(limit=50, force_close=True))


async def fetch_site(url):
    await _init_s()
    if not url.startswith(("http://", "https://")): url = "https://" + url
    domain = urlparse(url).netloc
    if domain in cache:
        e = cache[domain]
        if datetime.now() - e["t"] < timedelta(seconds=CACHE):
            return e["status"], e["html"], e["headers"]
    if domain in concurrent:
        while domain in concurrent: await asyncio.sleep(0.5)
        if domain in cache:
            e = cache[domain]
            return e["status"], e["html"], e["headers"]
    concurrent.add(domain)
    headers = {"accept": "text/html,*/*;q=0.8",
               "user-agent": "Mozilla/5.0 (Linux; Android 10) Chrome/140.0.0.0"}
    try:
        async with sem:
            async with _session.get(url, headers=headers, timeout=15) as r:
                t = await r.text(); st = r.status; h = dict(r.headers)
                cache[domain] = {"status": st, "html": t, "headers": h, "t": datetime.now()}
                return st, t, h
    except: return None, None, None
    finally: concurrent.discard(domain)


def det_cms(h):
    for cms, pat in CMS.items():
        if re.search(pat, h, re.I): return cms
    return "Unknown"


def det_sec(h):
    for p in [r'3d\s*secure', r'3ds', r'acsurl']:
        if re.search(p, h, re.I): return "3D Secure ✅"
    return "2D ❌"


def det_gw(h):
    out = []
    for g in PAY:
        if re.search(r'\b' + re.escape(g) + r'\b', h, re.I): out.append(g)
    return ", ".join(out) if out else "None"


def det_cap(h):
    hl = h.lower()
    if "hcaptcha" in hl: return "hCaptcha ✅"
    if "recaptcha" in hl: return "reCAPTCHA ✅"
    if "captcha" in hl: return "Captcha ✅"
    return "None"


def det_cf(h, headers, status):
    keys = [k.lower() for k in headers.keys()]
    if 'cf-ray' in keys or 'cloudflare' in headers.get('Server', '').lower():
        soup = BeautifulSoup(h, 'html.parser')
        title = soup.title.string.strip().lower() if soup.title else ''
        if any(i in title for i in ["just a moment", "checking your browser"]):
            return "Cloudflare Verification ✅"
        return "Cloudflare Present 🔍"
    return "None"


def det_gql(h):
    if re.search(r'/graphql|apollo-client', h, re.I): return "GraphQL ✅"
    return "None"


def fmt(url, cms, sec, gw, cap, cf, gql, status):
    d = urlparse(url).netloc
    return (f"{E.SEARCH} <b>Gate Check</b>\n"
            f"{E.GLOBE} URL: <code>{d}</code>\n"
            f"{E.CARD} Payments: <code>{gw}</code>\n"
            f"{E.SETTINGS} CMS: <code>{cms}</code>\n"
            f"{E.STATS} Status: <code>{status}</code>\n"
            f"{E.SHIELD} Security: <code>{sec}</code>\n"
            f"{E.LOCK} Captcha: <code>{cap}</code>\n"
            f"{E.FIRE} Cloudflare: <code>{cf}</code>\n"
            f"{E.COM} GraphQL: <code>{gql}</code>\n"
            f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")


def check_rate(uid):
    now = datetime.now()
    if uid in user_last:
        if (now - user_last[uid]).total_seconds() < RATE: return False
    user_last[uid] = now; return True


async def handle_gate_command(update, context):
    uid = update.effective_user.id
    if not check_rate(uid):
        await update.message.reply_text(f"⚠️ Wait {RATE}s.", parse_mode="HTML"); return
    if not context.args:
        await update.message.reply_text(f"{E.INFO} <code>/gate example.com</code>",
                                         parse_mode="HTML"); return
    url = context.args[0]
    if not url.startswith(("http://", "https://")): url = "https://" + url
    prog = await update.message.reply_text(
        f"🔄 <b>Scanning...</b>\n{E.GLOBE} <code>{url}</code>", parse_mode="HTML")
    try:
        st, h, headers = await fetch_site(url)
        if st is None:
            await prog.edit_text(f"{E.ERROR} Failed.", parse_mode="HTML"); return
        cms = det_cms(h); sec = det_sec(h); gw = det_gw(h)
        cap = det_cap(h); cf = det_cf(h, headers, st); gql = det_gql(h)
        await prog.edit_text(fmt(url, cms, sec, gw, cap, cf, gql, st), parse_mode="HTML")
    except Exception as e:
        logger.error(f"gate: {e}")
        await prog.edit_text(f"{E.ERROR} {e}", parse_mode="HTML")