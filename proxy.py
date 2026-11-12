"""proxy.py — Owner-only global proxy management
WITH detailed ipify live-check (error reason + IP returned + method label)
"""

import re, io, time, asyncio, aiohttp, logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from urllib.parse import quote

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from emojis import PremiumEmoji as E
from ui import primary, success, danger
from database import (
    add_proxy, get_user_proxies_new, get_user_active_proxies,
    delete_user_proxy_by_id, delete_all_user_proxies,
    update_proxy_status, get_total_user_proxies,
    get_total_user_active_proxies, get_total_proxies, clear_all_proxies,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# CHECK CONFIG
# ═══════════════════════════════════════════════
CHECK_ENDPOINT = "https://api.ipify.org?format=json"
CHECK_METHOD_LABEL = "ipify Live Check"
CHECK_ENDPOINT_LABEL = "api.ipify.org"
CONNECTION_TIMEOUT = 15
MAX_CONCURRENT_TESTS = 30
RETRY_DELAY = 0.2

# Legacy alias (some code may reference TEST_ENDPOINT)
TEST_ENDPOINT = CHECK_ENDPOINT

# ═══ STUCK-FIX: Global lock + hard timeouts ═══
_PROXY_OP_LOCK = asyncio.Lock()
_PROXY_TEST_MAX_SECONDS = 600
_PROXY_PER_CHECK_TIMEOUT = 20


def is_owner(uid):
    return uid == OWNER_ID


# ═══════════════════════════════════════════════
# RICH PROXY PARSER (from aiogram version)
# ═══════════════════════════════════════════════
def parse_proxy_input(proxy_input):
    """
    Comprehensive parser — handles 8 proxy formats:
      1. user:pass@ip:port
      2. user:pass ip:port
      3. ip:port user pass
      4. user pass ip:port
      5. user pass ip port
      6. user:pass:ip:port
      7. ip:port:user:pass
      8. ip:port (no auth)
    Protocol prefix (http/https/socks4/socks5) optional.
    """
    if not proxy_input or not proxy_input.strip():
        return None

    s = proxy_input.strip()
    if s.startswith('\ufeff'):
        s = s[1:]

    protocol = 'http'
    protocol_match = re.match(r'^(?P<p>http|https|socks4|socks5)://', s, re.IGNORECASE)
    if protocol_match:
        protocol = protocol_match.group('p').lower()
        s = s[len(protocol_match.group('p')) + 3:]

    def is_valid(ip, port):
        if not ip or not port:
            return False
        if not re.match(r'^([a-zA-Z0-9\-\.]+)$', ip):
            return False
        return port.isdigit() and 1 <= int(port) <= 65535

    def build(user, password, ip, port):
        eu = quote(user, safe='') if user else ''
        ep = quote(password, safe='') if password else ''
        if user and password:
            url_fmt  = f"{protocol}://{eu}:{ep}@{ip}:{port}"
            http_fmt = f"http://{user}:{password}@{ip}:{port}"
            db_fmt   = f"{user} {password} {ip} {port}"
        else:
            url_fmt  = f"{protocol}://{ip}:{port}"
            http_fmt = f"http://{ip}:{port}"
            db_fmt   = f"{ip} {port}"
        return {
            "user": user, "password": password, "ip": ip, "port": port,
            "original_format": proxy_input,
            "url_format": url_fmt, "http_format": http_fmt, "db_format": db_fmt,
        }

    patterns = [
        (r'^([^:@]+):([^:@]+)@([^:@]+):(\d+)$', ('u', 'p', 'i', 'port')),
        (r'^([^:@]+):([^:@]+)\s+([^:@]+):(\d+)$', ('u', 'p', 'i', 'port')),
        (r'^([^:@]+):(\d+)\s+([^:@]+)\s+([^:@]+)$', ('i', 'port', 'u', 'p')),
        (r'^([^:@]+)\s+([^:@]+)\s+([^:@]+):(\d+)$', ('u', 'p', 'i', 'port')),
        (r'^([^:@]+)\s+([^:@]+)\s+([^:@]+)\s+(\d+)$', ('u', 'p', 'i', 'port')),
        (r'^([^:@]+):([^:@]+):([^:@]+):(\d+)$', ('u', 'p', 'i', 'port')),
        (r'^([^:@]+):(\d+):([^:@]+):([^:@]+)$', ('i', 'port', 'u', 'p')),
        (r'^([^:@]+):(\d+)$', ('i', 'port')),
    ]

    for pat, keys in patterns:
        m = re.match(pat, s)
        if m:
            groups = m.groups()
            data = dict(zip(keys, groups))
            ip = data.get('i', '')
            port = data.get('port', '')
            if is_valid(ip, port):
                return build(data.get('u', ''), data.get('p', ''), ip, port)
    return None


# ── Simple parser (kept for DB compat) ──
def parse_proxy(proxy):
    if not proxy or not proxy.strip():
        return None
    proxy = proxy.strip().replace(" ", "")
    protocol = "http"
    pwp = proxy
    pat = r'^(https?|socks4|socks5)://'
    if re.match(pat, proxy):
        m = re.match(pat, proxy)
        protocol = m.group(1)
        pwp = re.sub(pat, '', proxy)
    parts = pwp.split(':')
    if len(parts) == 4 and '@' not in pwp:
        host, port, username, password = parts
        if '.' in host or ':' in host or host.replace('.', '').replace('-', '').isdigit():
            ue = quote(username, safe='')
            pe = quote(password, safe='')
            return {"protocol": protocol, "username": username, "password": password,
                    "host": host, "port": port,
                    "formatted": f"{protocol}://{ue}:{pe}@{host}:{port}"}
    if '@' in pwp:
        auth_part, host_part = pwp.split('@', 1)
        host_part = host_part.lstrip('@')
        if ':' in auth_part:
            username, password = auth_part.split(':', 1)
        else:
            username, password = auth_part, ''
        if ':' in host_part:
            host, port = host_part.split(':', 1)
        else:
            host, port = host_part, "8080"
        ue = quote(username, safe='')
        pe = quote(password, safe='')
        return {"protocol": protocol, "username": username, "password": password,
                "host": host, "port": port,
                "formatted": f"{protocol}://{ue}:{pe}@{host}:{port}"}
    if ':' in pwp and '@' not in pwp:
        if len(parts) == 2:
            host, port = parts
            return {"protocol": protocol, "username": None, "password": None,
                    "host": host, "port": port,
                    "formatted": f"{protocol}://{host}:{port}"}
    if '.' in pwp and ':' not in pwp:
        return {"protocol": protocol, "username": None, "password": None,
                "host": pwp, "port": "8080",
                "formatted": f"{protocol}://{pwp}:8080"}
    if '@@' in pwp:
        fixed = pwp.replace('@@', '@')
        return parse_proxy(f"{protocol}://{fixed}")
    if not proxy.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return parse_proxy(f"http://{proxy}")
    return None


def normalize_proxy(proxy):
    """Try rich parser first, fall back to simple."""
    pd = parse_proxy_input(proxy)
    if pd and pd.get("url_format"):
        return pd["url_format"]
    parsed = parse_proxy(proxy)
    if parsed and parsed["formatted"]:
        return parsed["formatted"]
    if not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
        return f"http://{proxy}"
    return proxy


def extract_proxies_from_text(text):
    """Extract proxies. Tries full line first (for space-separated formats),
    then splits on whitespace/comma."""
    proxies = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Try full line (handles space-separated formats like "user pass ip:port")
        if parse_proxy_input(line) or parse_proxy(line):
            if line not in seen:
                seen.add(line)
                proxies.append(line)
            continue
        # Fall back to split on commas/whitespace
        for part in re.split(r'[,\s\n]+', line):
            part = part.strip()
            if not part or part.startswith('#'):
                continue
            if parse_proxy_input(part) or parse_proxy(part):
                if part not in seen:
                    seen.add(part)
                    proxies.append(part)
    return proxies


# ═══════════════════════════════════════════════
# DETAILED LIVE CHECK
# ═══════════════════════════════════════════════
async def check_proxy_live(proxy_url, session=None, timeout=CONNECTION_TIMEOUT):
    """
    Live check against ipify.
    Returns (is_alive: bool, info: dict)
      info on success: {"ip": "1.2.3.4", "elapsed": 0.45}
      info on fail:    {"error": "Timeout"} / {"error": "HTTP 429"} / etc.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    client_timeout = aiohttp.ClientTimeout(total=timeout, connect=timeout / 2)
    close_session = False
    if session is None:
        session = aiohttp.ClientSession(timeout=client_timeout, headers=headers)
        close_session = True

    start = time.time()
    try:
        async with session.get(CHECK_ENDPOINT, proxy=proxy_url, ssl=False) as resp:
            elapsed = time.time() - start
            if resp.status == 200:
                try:
                    data = await resp.json()
                    ip = data.get('ip')
                    if ip:
                        return True, {"ip": ip, "elapsed": elapsed}
                    return False, {"error": "No IP in response"}
                except Exception:
                    text_data = await resp.text()
                    if text_data and text_data.strip():
                        return True, {"ip": text_data.strip(), "elapsed": elapsed}
                    return False, {"error": "Empty response"}
            elif resp.status == 429:
                return False, {"error": "Rate limited (429)"}
            else:
                return False, {"error": f"HTTP {resp.status}"}

    except asyncio.TimeoutError:
        return False, {"error": "Timeout"}
    except aiohttp.ClientProxyConnectionError:
        return False, {"error": "Proxy conn failed"}
    except aiohttp.ClientConnectorError:
        return False, {"error": "DNS/Conn error"}
    except aiohttp.ClientError as e:
        return False, {"error": f"Client error: {str(e)[:40]}"}
    except Exception as e:
        return False, {"error": str(e)[:60]}
    finally:
        if close_session:
            await session.close()


async def check_proxies_parallel(proxy_data_list, max_concurrent=MAX_CONCURRENT_TESTS):
    """
    Parallel check. proxy_data_list = list of parse_proxy_input dicts.
    Returns list of (proxy_data, is_live, info_dict).
    """
    if not proxy_data_list:
        return []
    sem = asyncio.Semaphore(max_concurrent)

    async def check_with_sem(pd):
        async with sem:
            try:
                is_live, info = await asyncio.wait_for(
                    check_proxy_live(pd['url_format']),
                    timeout=_PROXY_PER_CHECK_TIMEOUT)
                return (pd, is_live, info)
            except asyncio.TimeoutError:
                return (pd, False, {"error": "Hard timeout"})
            except Exception as e:
                return (pd, False, {"error": str(e)[:60]})

    tasks = [check_with_sem(p) for p in proxy_data_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            processed.append((proxy_data_list[i], False, {"error": str(r)[:60]}))
        else:
            processed.append(r)
    return processed


# Legacy wrappers (kept for backward compat with any code that imports them)
async def test_proxy(proxy):
    pc = normalize_proxy(proxy)
    is_live, info = await check_proxy_live(pc)
    if is_live:
        return True, info.get("elapsed", 0)
    return False, 0


async def test_proxies_batch(proxies, progress_cb=None):
    """Legacy batch — returns (proxy_str, ok, elapsed) tuples."""
    proxy_data_list = []
    for p in proxies:
        pd = parse_proxy_input(p)
        if not pd:
            pd = {"url_format": normalize_proxy(p), "http_format": p, "db_format": p}
        proxy_data_list.append(pd)

    results_detail = []
    total = len(proxy_data_list)
    for i in range(0, total, 10):
        batch = proxy_data_list[i:i + 10]
        batch_res = await check_proxies_parallel(batch)
        for pd, is_live, info in batch_res:
            elapsed = info.get("elapsed", 0) if is_live else 0
            results_detail.append((pd.get("db_format") or pd.get("http_format"), is_live, elapsed))
        if progress_cb:
            await progress_cb(min(i + 10, total), total)
        if i + 10 < total:
            await asyncio.sleep(RETRY_DELAY)
    return results_detail


def _deny_text():
    return (f"<blockquote>{E.ERROR} <b>Owner Only</b></blockquote>\n\n"
            f"<i>Proxies are managed globally.</i>\n\n"
            f"{E.LINK} <b>Contact</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")


# ═══════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════
async def proxy_command(update, context):
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return

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

    if not text:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Add Proxy (Global)</b></blockquote>\n\n"
            f"{E.NOTE} <b>Check:</b> <i>{CHECK_METHOD_LABEL}</i>\n"
            f"{E.GLOBE} <b>Endpoint:</b> <code>{CHECK_ENDPOINT_LABEL}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<code>/proxy user:pass@host:port</code>\n"
            f"<code>/proxy host:port:user:pass</code>\n"
            f"<code>/proxy user:pass host:port</code>\n"
            f"<code>/proxy host:port user pass</code>\n"
            f"<code>/proxy host:port</code>\n\n"
            f"<i>Or reply to .txt with proxies</i>",
            parse_mode="HTML")
        return

    raw = extract_proxies_from_text(text)
    if not raw:
        await update.message.reply_text(f"{E.ERROR} No valid proxies.", parse_mode="HTML")
        return

    existing = get_user_proxies_new(OWNER_ID)
    existing_strs = [p["proxy"] for p in existing]
    max_add = 9999 - len(existing)
    if max_add <= 0:
        await update.message.reply_text(f"{E.WARNING} Limit.", parse_mode="HTML")
        return
    if len(raw) > max_add:
        raw = raw[:max_add]

    proxies = []
    for p in raw:
        n = normalize_proxy(p)
        if n and (parse_proxy(n) or parse_proxy_input(n)):
            proxies.append(n)
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No valid formats.", parse_mode="HTML")
        return

    prog = await update.message.reply_text(
        f"<blockquote>{E.FLY} <b>Testing Proxies...</b></blockquote>\n<code>0/{len(proxies)}</code>",
        parse_mode="HTML")
    asyncio.create_task(_safe_test_wrapper(_run_test, proxies, existing_strs, prog, update, context))


async def _safe_test_wrapper(func, *args):
    """Lock + hard timeout wrapper for proxy tests."""
    _update = None
    for a in args:
        if hasattr(a, 'effective_chat'):
            _update = a
            break

    if _PROXY_OP_LOCK.locked():
        if _update:
            _msg = _update.effective_message
            if _msg:
                try:
                    await _msg.reply_text(
                        "⚠️ <b>Proxy test already running</b>\n"
                        "<i>Wait for it to finish, or /restart.</i>",
                        parse_mode="HTML")
                except: pass
        return

    async with _PROXY_OP_LOCK:
        try:
            await asyncio.wait_for(
                func(*args),
                timeout=_PROXY_TEST_MAX_SECONDS)
        except asyncio.TimeoutError:
            logger.error(f"{func.__name__} TIMEOUT after {_PROXY_TEST_MAX_SECONDS}s")
            if _update:
                _msg = _update.effective_message
                if _msg:
                    try:
                        await _msg.reply_text(
                            f"⏰ <b>Test timed out</b>\n"
                            f"<i>{_PROXY_TEST_MAX_SECONDS}s limit. "
                            f"Try fewer proxies at a time.</i>",
                            parse_mode="HTML")
                    except: pass
        except Exception as e:
            logger.error(f"{func.__name__} CRASH: {e}", exc_info=True)
            if _update:
                _msg = _update.effective_message
                if _msg:
                    try:
                        await _msg.reply_text(
                            f"❌ <b>Test failed</b>\n"
                            f"<code>{str(e)[:200]}</code>",
                            parse_mode="HTML")
                    except: pass


async def _run_test(proxies, existing_strs, prog, update, context):
    """Enhanced test with detailed error breakdown."""
    total = len(proxies)
    successful = []
    failed = []

    async def upd(done, total):
        try:
            await prog.edit_text(f"<blockquote>{E.FLY} <b>Testing...</b></blockquote>\n<code>{done}/{total}</code>",
                                  parse_mode="HTML")
        except: pass

    # Build proxy_data_list
    proxy_data_list = []
    for p in proxies:
        pd = parse_proxy_input(p)
        if not pd:
            pd = {"url_format": p, "http_format": p, "db_format": p}
        pd["_orig"] = p
        proxy_data_list.append(pd)

    # Chunked parallel check
    results = []
    for i in range(0, total, 10):
        batch = proxy_data_list[i:i + 10]
        batch_res = await check_proxies_parallel(batch)
        results.extend(batch_res)
        await upd(min(i + 10, total), total)
        if i + 10 < total:
            await asyncio.sleep(RETRY_DELAY)

    # Process
    live_count = 0
    dead_count = 0
    error_reasons = {}

    for pd, is_live, info in results:
        original = pd.get("_orig") or pd.get("db_format") or pd.get("http_format")
        normalized = original

        if is_live:
            live_count += 1
            if normalized in existing_strs:
                failed.append((normalized, "Duplicate"))
            else:
                if add_proxy(OWNER_ID, normalized):
                    rt = info.get("elapsed", 0)
                    for p in get_user_proxies_new(OWNER_ID):
                        if p["proxy"] == normalized:
                            update_proxy_status(p["id"], "active", rt)
                            break
                    successful.append((normalized, info.get("ip", "?")))
                else:
                    failed.append((normalized, "DB Error"))
        else:
            dead_count += 1
            reason = info.get("error", "Unknown")
            error_reasons[reason] = error_reasons.get(reason, 0) + 1
            failed.append((normalized, reason))

    # Build output
    st = "\n".join(f"• <code>{p.split('@')[-1]}</code> ✓" for p, _ in successful[:10])
    ft = "\n".join(f"• <code>{p.split('@')[-1]}</code> ✗" for p, r in failed[:10])

    result = (f"<blockquote>{E.SUCCESS} <b>Complete</b></blockquote>\n"
              f"━━━━━━━━━━━━━━━━━━\n"
              f"{E.APPROVED} <b>Success:</b> <code>{len(successful)}</code>\n")
    if st: result += f"<pre>{st}</pre>"
    result += f"\n{E.ERROR} <b>Failed:</b> <code>{len(failed)}</code>\n"
    if ft: result += f"<pre>{ft}</pre>"
    result += (f"\n━━━━━━━━━━━━━━━━━━\n"
               f"{E.STATS} <b>Total:</b> <code>{get_total_user_proxies(OWNER_ID)}</code>\n"
               f"{E.APPROVED} <b>Active:</b> <code>{get_total_user_active_proxies(OWNER_ID)}</code>\n\n"
               f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")
    _sent = False
    try:
        await prog.edit_text(result, parse_mode="HTML")
        _sent = True
    except Exception as _e1:
        logger.warning(f"[_run_test] edit failed: {_e1}")
    if not _sent:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=result,
                parse_mode="HTML")
            _sent = True
        except Exception as _e2:
            logger.error(f"[_run_test] send failed: {_e2}")
    if not _sent:
        try:
            await update.effective_message.reply_text(
                f"Proxy test done:\n"
                f"Live={live_count} Dead={dead_count} "
                f"Added={len(successful)} Failed={len(failed)}",
                parse_mode=None)
        except: pass


async def testproxy_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return
    proxies = get_user_proxies_new(OWNER_ID)
    if not proxies:
        await update.message.reply_text(f"{E.INFO} No proxies.", parse_mode="HTML")
        return
    msg = await update.message.reply_text(
        f"<blockquote>{E.FLY} <b>Testing {len(proxies)} proxies...</b></blockquote>\n<code>0/{len(proxies)}</code>",
        parse_mode="HTML")
    asyncio.create_task(_safe_test_wrapper(_tp_bg, proxies, msg, update, context))


async def _tp_bg(proxies, msg, update, context):
    total = len(proxies)

    async def upd(done, total):
        try:
            await msg.edit_text(f"<blockquote>{E.FLY} <b>Testing...</b></blockquote>\n<code>{done}/{total}</code>",
                                parse_mode="HTML")
        except: pass

    proxy_data_list = []
    for p in proxies:
        pd = parse_proxy_input(p["proxy"])
        if not pd:
            pd = {"url_format": p["proxy"], "http_format": p["proxy"],
                  "db_format": p["proxy"]}
        pd["_orig_id"] = p["id"]
        proxy_data_list.append(pd)

    results = []
    for i in range(0, total, 10):
        batch = proxy_data_list[i:i + 10]
        batch_res = await check_proxies_parallel(batch)
        results.extend(batch_res)
        await upd(min(i + 10, total), total)
        if i + 10 < total:
            await asyncio.sleep(RETRY_DELAY)

    active = 0
    deleted = 0
    error_reasons = {}

    for pd, is_live, info in results:
        pid = pd.get("_orig_id")
        if not pid:
            continue
        if is_live:
            active += 1
            rt = info.get("elapsed", 0)
            update_proxy_status(pid, "active", rt)
        else:
            reason = info.get("error", "Unknown")
            error_reasons[reason] = error_reasons.get(reason, 0) + 1
            delete_user_proxy_by_id(pid, OWNER_ID)
            deleted += 1

    result = (f"<blockquote>{E.SUCCESS} <b>Complete</b></blockquote>\n"
              f"━━━━━━━━━━━━━━━━━━\n"
              f"📊 Tested: <code>{total}</code>\n"
              f"{E.APPROVED} Active: <code>{active}</code>\n"
              f"{E.ERROR} Dead: <code>{total - active}</code>\n"
              f"{E.CLOSE} Deleted: <code>{deleted}</code>\n\n"
              f"📈 Total: <code>{get_total_user_proxies(OWNER_ID)}</code>\n"
              f"{E.STAR} Active: <code>{get_total_user_active_proxies(OWNER_ID)}</code>\n\n"
              f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")
    _sent = False
    try:
        await msg.edit_text(result, parse_mode="HTML")
        _sent = True
    except Exception as _e1:
        logger.warning(f"[_tp_bg] edit failed: {_e1}")
    if not _sent:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=result,
                parse_mode="HTML")
            _sent = True
        except Exception as _e2:
            logger.error(f"[_tp_bg] send failed: {_e2}")
    if not _sent:
        try:
            await update.effective_message.reply_text(
                f"Recheck done:\nActive={active} Deleted={deleted}",
                parse_mode=None)
        except: pass


# ═══════════════════════════════════════════════
# UNCHANGED COMMANDS
# ═══════════════════════════════════════════════
async def getproxy_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return
    proxies = get_user_proxies_new(OWNER_ID)
    if not proxies:
        await update.message.reply_text(f"{E.INFO} No proxies.", parse_mode="HTML")
        return
    content = "\n".join(p["proxy"] for p in proxies)
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f"proxies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    caption = (f"<blockquote>{E.GLOBE} <b>All Proxies</b></blockquote>\n"
               f"{E.STATS} <b>Total:</b> <code>{len(proxies)}</code>\n"
               f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>")
    await update.message.reply_document(document=file, caption=caption, parse_mode="HTML")
    file.close()


async def rmproxy_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/rmproxy ID</code>", parse_mode="HTML")
        return
    try:
        pid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid ID.", parse_mode="HTML")
        return
    if delete_user_proxy_by_id(pid, OWNER_ID):
        await update.message.reply_text(
            f"{E.SUCCESS} Deleted.\n{E.STATS} <b>Remaining:</b> <code>{get_total_user_proxies(OWNER_ID)}</code>",
            parse_mode="HTML")
    else:
        await update.message.reply_text(f"{E.ERROR} Not found.", parse_mode="HTML")


async def clearproxy_command(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(_deny_text(), parse_mode="HTML")
        return
    if context.args and context.args[0].lower() == "confirm":
        n = delete_all_user_proxies(OWNER_ID)
        await update.message.reply_text(f"{E.SUCCESS} All {n} proxies deleted.", parse_mode="HTML")
        return
    total = get_total_user_proxies(OWNER_ID)
    kb = InlineKeyboardMarkup([[
        danger("Confirm", "proxy_clear_confirm"),
        primary("Cancel", "proxy_clear_cancel")]])
    await update.message.reply_text(
        f"{E.WARNING} <b>Confirm?</b>\n\nDelete ALL <code>{total}</code> global proxies?",
        parse_mode="HTML", reply_markup=kb)


async def proxy_clear_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not is_owner(q.from_user.id):
        await q.answer("Owner only", show_alert=True)
        return
    if q.data == "proxy_clear_cancel":
        await q.edit_message_text(f"{E.INFO} Cancelled.", parse_mode="HTML")
        return
    n = delete_all_user_proxies(OWNER_ID)
    await q.edit_message_text(f"{E.SUCCESS} All {n} proxies deleted.", parse_mode="HTML")


async def handle_proxies_view(update, context):
    q = update.callback_query
    await q.answer()
    if not is_owner(q.from_user.id):
        await q.answer("Owner only", show_alert=True)
        return
    proxies = get_user_proxies_new(OWNER_ID)
    if not proxies:
        await q.edit_message_text(f"{E.INFO} <b>No Proxies</b>\n\n<i>/proxy to add.</i>", parse_mode="HTML")
        return
    lines = []
    for i, p in enumerate(proxies[:20], 1):
        status = "✅" if p["status"] == "active" else "❌"
        host = p["proxy"].split("@")[-1] if "@" in p["proxy"] else p["proxy"][:40]
        lines.append(f"<code>{p['id']}</code>. {status} {host}")
    await q.edit_message_text(
        f"<blockquote>{E.SUCCESS} <b>Global Proxies</b></blockquote>\n"
        f"{E.STATS} <b>Count:</b> <code>{len(proxies)}</code>\n"
        f"<pre>{chr(10).join(lines)}</pre>",
        parse_mode="HTML")


def register_proxy(app):
    app.add_handler(CommandHandler("proxy", proxy_command))
    app.add_handler(CommandHandler("tp", testproxy_command))
    app.add_handler(CommandHandler("getproxy", getproxy_command))
    app.add_handler(CommandHandler("rmproxy", rmproxy_command))
    app.add_handler(CommandHandler("clearproxy", clearproxy_command))
    app.add_handler(CallbackQueryHandler(proxy_clear_callback, pattern="^proxy_clear_"))
    app.add_handler(CallbackQueryHandler(handle_proxies_view, pattern="^menu_proxies_view$"))
