"""api_config.py — API endpoint + site toggle + timeout config"""

import json, logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID, BOT_NAME, API_TIMEOUT
from database import is_db_admin
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parent / "api_config.json"
_DEFAULT_ENDPOINT    = "http://209.46.121.203:8081"
_DEFAULT_SITE_ENABLED = True

_current_endpoint    = None
_current_site_enabled = None


def _load():
    global _current_endpoint, _current_site_enabled
    if _current_endpoint is not None:
        return _current_endpoint
    try:
        if _CONFIG_PATH.exists():
            d = json.loads(_CONFIG_PATH.read_text())
            _current_endpoint     = d.get("endpoint", _DEFAULT_ENDPOINT)
            _current_site_enabled = bool(d.get("site_enabled", _DEFAULT_SITE_ENABLED))
        else:
            _current_endpoint     = _DEFAULT_ENDPOINT
            _current_site_enabled = _DEFAULT_SITE_ENABLED
    except Exception:
        _current_endpoint     = _DEFAULT_ENDPOINT
        _current_site_enabled = _DEFAULT_SITE_ENABLED
    return _current_endpoint


def _save():
    try:
        _CONFIG_PATH.write_text(json.dumps({
            "endpoint":     _current_endpoint,
            "site_enabled": bool(_current_site_enabled),
        }, indent=2))
    except Exception: pass


def _normalize(url):
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if "?" in url:
        base, q = url.split("?", 1)
        parts = [p.strip() for p in q.split("&") if p.strip()]
        known = {"site", "cc", "proxy", "number", "amount", "gate"}
        def _empty(p):
            if "=" not in p: return True
            k, v = p.split("=", 1)
            return k in known and v == ""
        if parts and all(_empty(x) for x in parts):
            url = base
    return url


def get_current_endpoint():
    _load()
    return _current_endpoint


def get_site_enabled():
    _load()
    return _current_site_enabled


# ── Aliases — used by sh.py / msh.py / sites.py ──
def get_api_endpoint():
    return get_current_endpoint()


def is_site_enabled():
    return get_site_enabled()


def get_api_timeout():
    return API_TIMEOUT


async def capi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _current_endpoint, _current_site_enabled
    user = update.effective_user
    if user.id != OWNER_ID and not is_db_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    _load()

    if not context.args:
        await update.message.reply_text(
            f"<blockquote>{E.KEY} <b>API Config</b></blockquote>\n\n"
            f"{E.GLOBE} <b>Endpoint:</b> <code>{_current_endpoint}</code>\n"
            f"{E.APPROVED} <b>Site:</b> <code>{'enabled' if _current_site_enabled else 'disabled'}</code>\n"
            f"{E.CLOCK} <b>Timeout:</b> <code>{API_TIMEOUT}s</code>\n\n"
            f"<b>Usage:</b>\n"
            f"<code>/capi URL</code> — with site\n"
            f"<code>/capi URL nosite</code> — without site\n"
            f"<code>/capi reset</code> — reset to default",
            parse_mode="HTML")
        return

    if context.args[0].lower() == "reset":
        _current_endpoint     = _DEFAULT_ENDPOINT
        _current_site_enabled = _DEFAULT_SITE_ENABLED
        _save()
        await update.message.reply_text(f"{E.SUCCESS} Reset to default.", parse_mode="HTML")
        return

    raw = context.args[0]
    nosite = len(context.args) > 1 and context.args[1].lower() == "nosite"
    _current_endpoint     = _normalize(raw)
    _current_site_enabled = not nosite
    _save()

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>API Updated</b></blockquote>\n"
        f"{E.GLOBE} <b>Endpoint:</b> <code>{_current_endpoint}</code>\n"
        f"{E.APPROVED} <b>Site:</b> <code>{'enabled' if _current_site_enabled else 'disabled'}</code>\n"
        f"{E.CLOCK} <b>Timeout:</b> <code>{API_TIMEOUT}s</code>",
        parse_mode="HTML")


def register_capi(app):
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("capi", capi))
