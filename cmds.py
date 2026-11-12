"""cmds.py — Role-based command menu"""

import logging, html
from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from emojis import PremiumEmoji as E
from ui import primary, success, danger
from config import OWNER_ID
from database import is_db_admin

logger = logging.getLogger(__name__)


def escape_html(text): return html.escape(text, quote=False)


ALL_COMMANDS = [
    ("Shopify", "/sh", "Free", "Single Shopify charge", "sh"),
    ("Shopify Mass", "/msh", "Paid", "Mass Shopify check", "msh"),
    ("Braintree 3DS2", "/vbv", "Free", "3DS / VBV lookup", "vbv"),
    ("Card generator", "/gen", "Free", "Generate Luhn cards", "gen"),
    ("Site scanner", "/gate", "Free", "Scan website info", "gate"),
    ("Check credits", "/credits", "Free", "Your credit balance", None),
    ("Commands menu", "/cmds", "Free", "This menu", None),
    ("Bot status", "/status", "Free", "VPS + bot stats", None),
    ("Send feedback", "/fb", "Free", "Send feedback", "fb"),
    ("Redeem code", "/claim", "Free", "Redeem a code", None),
    ("Stop session", "/stop", "Free", "Stop mass session", None),
    ("Jio Hitter", "/jhit", "Paid", "Jio bill hitter", None),
    ("Admin panel", "/admin", "Admin", "Admin control", None),
    ("Active sessions", "/session", "Admin", "View sessions", None),
    ("Stop session admin", "/stopsession", "Admin", "Force stop", None),
    ("VPS detailed", "/vps", "Admin", "VPS stats", None),
    ("Clear proxies", "/clear proxy", "Admin", "Wipe proxies", None),
    ("Grant plan", "/auth", "Admin", "Give plan", None),
    ("Revoke plan", "/unauth", "Admin", "Remove plan", None),
    ("Plan 1 Core", "/plan1", "Admin", "Core 7d", None),
    ("Plan 2 Elite", "/plan2", "Admin", "Elite 15d", None),
    ("Plan 3 Root", "/plan3", "Admin", "Root 30d", None),
    ("Plan 4 X", "/plan4", "Admin", "X 90d", None),
    ("Revoke plan alt", "/rplan", "Admin", "Revoke", None),
    ("List plans", "/planall", "Admin", "List active", None),
    ("Deduct credits", "/decreds", "Admin", "Deduct", None),
    ("Ban user", "/ban", "Admin", "Ban", None),
    ("Unban user", "/unban", "Admin", "Unban", None),
    ("Generate key", "/genkey", "Admin", "Gen key", None),
    ("Delete key", "/delkey", "Admin", "Del key", None),
    ("Plan codes", "/gplan1-4", "Admin", "Bulk plan codes", None),
    ("Credit codes", "/gcodes", "Admin", "Bulk credit codes", None),
    ("Add sites", "/addsite", "Owner", "Add global sites", None),
    ("Test all sites", "/ts", "Owner", "Validate sites", None),
    ("Export sites", "/getsite", "Owner", "Export sites", None),
    ("Remove site", "/rmsite", "Owner", "Delete site", None),
    ("Clear sites", "/clearsites", "Owner", "Wipe sites", None),
    ("Add proxies", "/proxy", "Owner", "Add proxies", None),
    ("Test proxies", "/tp", "Owner", "Validate proxies", None),
    ("Export proxies", "/getproxy", "Owner", "Export proxies", None),
    ("Remove proxy", "/rmproxy", "Owner", "Delete ID", None),
    ("Clear proxies", "/clearproxy", "Owner", "Wipe proxies", None),
    ("Add admin", "/addadmin", "Owner", "Add admin", None),
    ("Remove admin", "/rmadmin", "Owner", "Remove admin", None),
    ("Set Jio Number", "/setnum", "Owner", "Set number for jchk", None),
    ("Remove Jio Number", "/rmvnum", "Owner", "Remove jchk number", None),
    ("Check Jio Number", "/cknum", "Owner", "Show current jchk number", None),
    ("Lock Bot", "/lock", "Owner", "Lock the bot", None),
    ("Unlock Bot", "/unlock", "Owner", "Unlock the bot", None),
    ("Broadcast", "/broad", "Owner", "Broadcast", None),
    ("Set API", "/capi", "Owner", "Set API URL", None),
]

PAGE_SIZE = 6


def get_commands_for_user(user_id):
    is_owner = (user_id == OWNER_ID)
    is_admin = is_owner or is_db_admin(user_id)
    out = []
    for cmd in ALL_COMMANDS:
        _, _, tier, _, _ = cmd
        if tier in ("Free", "Paid"): out.append(cmd)
        elif tier == "Admin" and is_admin: out.append(cmd)
        elif tier == "Owner" and is_owner: out.append(cmd)
    return out


def get_pages(user_id):
    cmds = get_commands_for_user(user_id)
    return [cmds[i:i + PAGE_SIZE] for i in range(0, len(cmds), PAGE_SIZE)]


async def build_page_text(page_index, user_id):
    pages = get_pages(user_id)
    total_pages = len(pages)
    if total_pages == 0: return ("No commands.", 0)
    page = pages[page_index]
    is_owner = (user_id == OWNER_ID)
    is_admin = is_owner or is_db_admin(user_id)
    if is_owner: badge = f"{E.CROWN} <b>OWNER</b>"
    elif is_admin: badge = f"{E.SHIELD} <b>ADMIN</b>"
    else: badge = f"{E.USER} <b>USER</b>"
    text = (f"<blockquote>{E.SEARCH} <b>𝑪𝒐𝒎𝒎𝒂𝒏𝒅𝒔</b> ↬ <i>Page {page_index + 1}/{total_pages}</i></blockquote>\n"
            f"{badge} • <i>{len(get_commands_for_user(user_id))} commands</i>\n"
            "━━━━━━━━━━━━━━━━━━\n")
    for name, cmd, ctype, desc, _g in page:
        if ctype == "Paid": icon = E.STAR
        elif ctype == "Admin": icon = E.SHIELD
        elif ctype == "Owner": icon = E.CROWN
        else: icon = E.THUNDER
        text += (f"{icon} <b>{escape_html(name)}</b>\n"
                 f"{E.RIGHT} <b>Command</b> ➠ <code>{escape_html(cmd)}</code>\n"
                 f"{E.NOTE} <b>Info</b> ➠ <i>{escape_html(desc)}</i>\n"
                 f"{E.LOCK if ctype in ('Admin', 'Owner', 'Paid') else E.APPROVED} <b>Type</b> ➠ <i>{ctype}</i>\n"
                 "━━━━━━━━━━━━━━━━━━\n")
    text += f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/CARDERxRDX'>𝙍𝘿𝙓</a>"
    return text.strip(), total_pages


def build_cmds_buttons(page_index, total_pages):
    nav = []
    if page_index > 0: nav.append(primary("⬅️ Prev", f"cmds_page_{page_index-1}"))
    nav.append(primary(f"{page_index+1}/{total_pages}", "ignore"))
    if page_index < total_pages - 1: nav.append(success("Next ➡️", f"cmds_page_{page_index+1}"))
    buttons = [nav] if nav else []
    buttons.append([danger("❌ Close", "cmds_close")])
    return InlineKeyboardMarkup(buttons)


async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text, total = await build_page_text(0, user_id)
    if total == 0:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML); return
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     disable_web_page_preview=True,
                                     reply_markup=build_cmds_buttons(0, total))


async def cmds_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data; user_id = update.effective_user.id
    if data.startswith("cmds_page_"):
        try:
            idx = int(data.split("_")[2])
            text, total = await build_page_text(idx, user_id)
            if total == 0: return
            if idx >= total:
                idx = total - 1
                text, total = await build_page_text(idx, user_id)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True,
                                       reply_markup=build_cmds_buttons(idx, total))
        except TelegramError as e:
            if "not modified" not in str(e): logger.error(f"cmds: {e}")
    elif data == "cmds_close":
        try: await q.message.delete()
        except TelegramError: await q.edit_message_text("Closed.")