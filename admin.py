"""admin.py — Full admin panel: broadcast, backup/restore, LB, force join config, API keys"""

import time, logging, asyncio, os, io, sys, gzip, shutil, tempfile
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

from config import (START_PHOTO, OWNER_ID, BOT_NAME, DEV_ID, API_TIMEOUT)
from database import (
    is_db_admin, get_total_users, get_total_premium, get_total_banned,
    get_total_admins, get_total_sites, get_total_proxies, get_unclaimed_keys,
    get_all_active_plans, get_all_user_ids, get_all_banned_users,
    get_all_admins, get_daily_stats, get_user_credits,
    backup_database, restore_database, get_pending_proofs, update_proof_status,
    get_all_load_balancers, get_active_load_balancers, DB_PATH
)
from emojis import PremiumEmoji as E
from anime_image import get_anime_image
from ui import primary, success, danger

logger = logging.getLogger(__name__)

# State: uid -> what admin is currently inputting
_admin_state: dict[int, str] = {}

# ─────────────────────────────────────────────
# DASHBOARD TEXT + KEYBOARD
# ─────────────────────────────────────────────

def get_admin_dashboard_text(uid):
    users   = get_total_users()
    premium = get_total_premium()
    banned  = get_total_banned()
    admins  = get_total_admins()
    sites   = get_total_sites()
    proxies = get_total_proxies()
    keys    = get_unclaimed_keys()
    pool    = sites + proxies
    proofs  = len(get_pending_proofs())
    lbs     = len(get_all_load_balancers())
    active_lbs = len(get_active_load_balancers())

    return (
        f"<blockquote>{E.SHIELD} <b>ADMIN PANEL</b> {E.SHIELD}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USERS} <b>Total Users</b> · <code>{users}</code>\n"
        f"{E.STAR} <b>Active Subs</b> · <code>{premium}</code>\n"
        f"{E.BAN} <b>Banned</b> · <code>{banned}</code>\n"
        f"{E.SHIELD} <b>Admins</b> · <code>{admins}</code>\n"
        f"{E.GLOBE} <b>Global Pool</b> · <code>{pool}</code>\n"
        f"{E.KEY} <b>Unclaimed Keys</b> · <code>{keys}</code>\n"
        f"{E.FILE} <b>Pending Proofs</b> · <code>{proofs}</code>\n"
        f"{E.SPEED} <b>Load Balancers</b> · <code>{active_lbs}/{lbs} active</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>{BOT_NAME}</b>"
    )


def get_admin_keyboard(uid):
    from emojis import ButtonEmoji as BE
    is_owner = (uid == OWNER_ID)

    rows = [
        [primary("👥 Users",        "admin_menu_users",    icon=BE.USERS),
         primary("📊 Stats",        "admin_menu_stats",    icon=BE.STATS_EMOJI)],
        [danger( "📢 Broadcast All","admin_broad_all",     icon=BE.FIRE),
         success("💎 Broadcast Sub","admin_broad_prem",    icon=BE.PREMIUM)],
        [danger( "🚫 Banned List",  "admin_banned_list",   icon=BE.BAN)],
        [primary("📈 Analytics",    "admin_analytics",     icon=BE.STATS_EMOJI)],
        [primary("💾 Backup Now",   "admin_backup_db",     icon=BE.DOWNLOAD),
         success("♻️ Restore DB",   "admin_restore_db",    icon=BE.REDEEM)],
        [primary("⚡ Load Balancers","menu_lb",            icon=BE.THUNDER)],
        [primary("🔗 Force Join",   "admin_forcejoin",     icon=BE.GATES)],
        [primary("🔑 API Keys",     "admin_api_keys",      icon=BE.KEYS)],
        [success("📋 Admin Cmds",   "admin_cmds_admin",    icon=BE.SETTINGS_EMOJI)],
    ]

    if is_owner:
        rows[2].append(primary("👑 Admins List", "admin_admins_list", icon=BE.ADMIN))
        rows.append([danger("👑 Owner Cmds", "admin_cmds_owner", icon=BE.VIEW)])

    rows.append([primary("Back", "back_main"), danger("Close", "close_menu")])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────
# BROADCAST (preserve formatting via copy)
# ─────────────────────────────────────────────

async def _run_broadcast(bot, chat_id, message, premium_only=False):
    if premium_only:
        plans = get_all_active_plans()
        target_uids = [p[0] for p in plans if p[2] and p[2] > datetime.now()]
        if OWNER_ID not in target_uids: target_uids.append(OWNER_ID)
    else:
        target_uids = get_all_user_ids()

    msg = await bot.send_message(chat_id, f"🚀 <b>Broadcasting to {len(target_uids)} users...</b>", parse_mode="HTML")
    sent = 0
    for i, uid in enumerate(target_uids, 1):
        try:
            if isinstance(message, str):
                await bot.send_message(chat_id=uid, text=message, parse_mode="HTML")
            else:
                # copy preserves spoiler, quote, mono, etc.
                await message.copy(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
        if i % 25 == 0:
            try: await msg.edit_text(f"🚀 Broadcasting...\nSent: {sent}/{len(target_uids)}", parse_mode="HTML")
            except: pass

    await msg.edit_text(f"✅ <b>Broadcast Complete!</b>\nSent to: <code>{sent}</code> users.", parse_mode="HTML")


# ─────────────────────────────────────────────
# /admin COMMAND
# ─────────────────────────────────────────────

async def admin(update, context):
    user = update.effective_user
    if user.id != OWNER_ID and not is_db_admin(user.id):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Access Denied</b></blockquote>\n\n"
            f"<i>Admins only.</i>", parse_mode="HTML")
        return

    text = get_admin_dashboard_text(user.id)
    kb   = get_admin_keyboard(user.id)
    try:
        image_url = await get_anime_image()
    except Exception:
        image_url = START_PHOTO
    try:
        await update.message.reply_photo(photo=image_url, caption=text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

async def admin_panel_callbacks(update, context):
    q   = update.callback_query
    data = q.data
    uid  = q.from_user.id

    try: await q.answer()
    except: pass

    if not (uid == OWNER_ID or is_db_admin(uid)):
        return

    # ── Dashboard ──
    if data == "menu_admin":
        text = get_admin_dashboard_text(uid)
        kb   = get_admin_keyboard(uid)
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except:
            try: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            except: pass
        return

    # ── Users ──
    if data == "admin_menu_users":
        text = (
            f"<blockquote>{E.USERS} <b>User Management</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.RIGHT} <code>/auth UID DAYS</code> — Grant Plan\n"
            f"{E.RIGHT} <code>/unauth UID</code> — Remove Plan\n"
            f"{E.RIGHT} <code>/ban UID</code> — Ban User\n"
            f"{E.RIGHT} <code>/unban UID</code> — Unban User\n"
            f"{E.RIGHT} <code>/info UID</code> — Check User\n"
            f"{E.RIGHT} <code>/planall</code> — All Active Plans\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Stats ──
    if data == "admin_menu_stats":
        daily = get_daily_stats()
        text = (
            f"<blockquote>{E.STATS} <b>Today's Stats</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.CARD} <b>Checked</b> ➠ <code>{daily['total']:,}</code>\n"
            f"{E.FIRE} <b>Charged</b> ➠ <code>{daily['charged']:,}</code>\n"
            f"{E.APPROVED} <b>Approved</b> ➠ <code>{daily['approved']:,}</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Broadcast buttons ──
    if data in ("admin_broad_all", "admin_broad_prem"):
        prem = (data == "admin_broad_prem")
        _admin_state[uid] = f"broadcast_{'prem' if prem else 'all'}"
        await q.message.reply_text(
            f"<blockquote>{E.FIRE} <b>Broadcast</b></blockquote>\n\n"
            f"Reply to this message with your broadcast content.\n"
            f"{'Premium users only.' if prem else 'All users.'}\n\n"
            f"{E.INFO} <i>Supports: text, spoiler, mono, quoted, photo, document.</i>",
            parse_mode="HTML",
            reply_markup=ForceReply(selective=True)
        )
        return

    # ── Backup Now ──
    if data == "admin_backup_db":
        try:
            await q.edit_message_text(
                f"<blockquote>{E.LOAD} <b>Creating Backup...</b></blockquote>",
                parse_mode="HTML")
        except: pass

        from backup_scheduler import send_backup
        ok = await send_backup(context.bot, uid, label="Manual")
        result = "✅ Backup sent!" if ok else "❌ Backup failed."
        try:
            kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
            await q.edit_message_text(
                f"<blockquote>{E.DATABASE} <b>Backup</b></blockquote>\n{result}",
                parse_mode="HTML", reply_markup=kb)
        except: pass
        return

    # ── Restore DB ──
    if data == "admin_restore_db":
        _admin_state[uid] = "restore_db"
        await q.message.reply_text(
            f"<blockquote>{E.REFRESH} <b>Restore Database</b></blockquote>\n\n"
            f"Send the <code>.db</code> backup file (not gzipped).\n"
            f"{E.WARNING} <b>This will overwrite current data.</b>",
            parse_mode="HTML",
            reply_markup=ForceReply(selective=True)
        )
        return

    # ── Banned List ──
    if data == "admin_banned_list":
        bans = get_all_banned_users()
        if not bans:
            text = f"<blockquote>{E.BAN} <b>Banned Users</b></blockquote>\n\n<i>No banned users.</i>"
        else:
            lines = "\n".join(f"{E.RIGHT} <code>{uid_}</code> — {r or 'No reason'}" for uid_, r in bans[:30])
            text = f"<blockquote>{E.BAN} <b>Banned ({len(bans)})</b></blockquote>\n━━━━━━━━━━━━━━━━━━\n{lines}"
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Admins List ──
    if data == "admin_admins_list":
        if uid != OWNER_ID:
            await q.answer("Owner only", show_alert=True); return
        admins = get_all_admins()
        lines = "\n".join(f"{E.RIGHT} <code>{a}</code>" for a in admins) or "<i>No admins.</i>"
        text = f"<blockquote>{E.SHIELD} <b>Admins ({len(admins)})</b></blockquote>\n━━━━━━━━━━━━━━━━━━\n{lines}"
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Analytics ──
    if data == "admin_analytics":
        daily = get_daily_stats()
        text = (
            f"<blockquote>{E.STATS} <b>Analytics</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.CARD} Today Checked ➠ <code>{daily['total']:,}</code>\n"
            f"{E.FIRE} Today Charged ➠ <code>{daily['charged']:,}</code>\n"
            f"{E.APPROVED} Today Approved ➠ <code>{daily['approved']:,}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.INFO} Use /stats for full leaderboard."
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Force Join Config ──
    if data == "admin_forcejoin":
        from database import get_force_join_config
        cfg = get_force_join_config()
        text = (
            f"<blockquote>{E.GATES} <b>Force Join Config</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.GLOBE} Group Link: <code>{cfg.get('gc_link', 'not set')}</code>\n"
            f"{E.GLOBE} Channel Link: <code>{cfg.get('channel_link', 'not set')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Use /setgc and /setchannel to update."
        )
        kb = InlineKeyboardMarkup([
            [primary("Set GC Link", "admin_set_gc"), primary("Set Channel", "admin_set_channel")],
            [primary("Back", "menu_admin")]
        ])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "admin_set_gc":
        _admin_state[uid] = "set_gc"
        await q.message.reply_text(
            f"Send the new GC invite link:", reply_markup=ForceReply(selective=True))
        return

    if data == "admin_set_channel":
        _admin_state[uid] = "set_channel"
        await q.message.reply_text(
            f"Send the new Channel invite link:", reply_markup=ForceReply(selective=True))
        return

    # ── API Keys ──
    if data == "admin_api_keys":
        from api_config import get_current_endpoint, get_site_enabled
        ep = get_current_endpoint()
        se = get_site_enabled()
        text = (
            f"<blockquote>{E.KEY} <b>API Configuration</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.GLOBE} <b>Endpoint</b> ➠ <code>{ep}</code>\n"
            f"{E.APPROVED} <b>Site Enabled</b> ➠ <code>{'Yes' if se else 'No'}</code>\n"
            f"{E.CLOCK} <b>Timeout</b> ➠ <code>{API_TIMEOUT}s</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.INFO} Use /capi to set endpoint.\n"
            f"/capi URL — with site\n"
            f"/capi URL nosite — without site"
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # ── Admin Cmds ──
    if data == "admin_cmds_admin":
        text = (
            f"<blockquote>{E.SETTINGS} <b>Admin Commands</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.RIGHT} <code>/auth UID DAYS</code>\n"
            f"{E.RIGHT} <code>/unauth UID</code>\n"
            f"{E.RIGHT} <code>/ban UID [reason]</code>\n"
            f"{E.RIGHT} <code>/unban UID</code>\n"
            f"{E.RIGHT} <code>/info UID</code>\n"
            f"{E.RIGHT} <code>/genkey DAYS TIER</code>\n"
            f"{E.RIGHT} <code>/delkey CODE</code>\n"
            f"{E.RIGHT} <code>/gcodes</code>\n"
            f"{E.RIGHT} <code>/broad MSG</code>\n"
            f"{E.RIGHT} <code>/capi URL</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "admin_cmds_owner":
        if uid != OWNER_ID:
            await q.answer("Owner only", show_alert=True); return
        text = (
            f"<blockquote>{E.CROWN} <b>Owner Commands</b></blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.RIGHT} <code>/addadmin UID</code>\n"
            f"{E.RIGHT} <code>/rmadmin UID</code>\n"
            f"{E.RIGHT} <code>/lock</code> / <code>/unlock</code>\n"
            f"{E.RIGHT} <code>/speed N</code>\n"
            f"{E.RIGHT} <code>/addsite URL</code>\n"
            f"{E.RIGHT} <code>/rmsite URL</code>\n"
            f"{E.RIGHT} <code>/proxy add TYPE:HOST:PORT</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([[primary("Back", "menu_admin")]])
        try: await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        except: await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return


# ─────────────────────────────────────────────
# MESSAGE HANDLER (broadcast reply, restore, GC/channel)
# ─────────────────────────────────────────────

async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if not (uid == OWNER_ID or is_db_admin(uid)):
        return

    state = _admin_state.get(uid)
    if not state:
        return

    msg = update.message

    # Broadcast
    if state.startswith("broadcast_"):
        _admin_state.pop(uid, None)
        prem = state.endswith("prem")
        content = msg.text or msg.caption
        if content:
            asyncio.create_task(_run_broadcast(context.bot, uid, msg, premium_only=prem))
        else:
            asyncio.create_task(_run_broadcast(context.bot, uid, msg, premium_only=prem))
        await msg.reply_text(f"<blockquote>{E.FIRE} <b>Broadcast queued.</b></blockquote>", parse_mode="HTML")
        return

    # Restore DB
    if state == "restore_db":
        _admin_state.pop(uid, None)
        if not msg.document:
            await msg.reply_text(f"{E.ERROR} Send a .db file.", parse_mode="HTML")
            return
        fname = msg.document.file_name or ""
        if not fname.endswith(".db"):
            await msg.reply_text(f"{E.ERROR} File must be a <code>.db</code> file.", parse_mode="HTML")
            return
        wait = await msg.reply_text(f"<blockquote>{E.LOAD} Downloading and restoring...</blockquote>", parse_mode="HTML")
        try:
            tg_file = await context.bot.get_file(msg.document.file_id)
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            await tg_file.download_to_drive(tmp.name)
            ok, result_msg = restore_database(tmp.name)
            try: os.remove(tmp.name)
            except: pass
            icon = E.SUCCESS if ok else E.ERROR
            await wait.edit_text(
                f"<blockquote>{icon} <b>{'Restore OK' if ok else 'Restore Failed'}</b></blockquote>\n{result_msg}",
                parse_mode="HTML")
        except Exception as e:
            await wait.edit_text(f"{E.ERROR} Error: <code>{e}</code>", parse_mode="HTML")
        return

    # Set GC link
    if state == "set_gc":
        _admin_state.pop(uid, None)
        from database import set_force_join_config
        set_force_join_config("gc_link", msg.text.strip())
        await msg.reply_text(f"{E.SUCCESS} GC link updated.", parse_mode="HTML")
        return

    # Set channel link
    if state == "set_channel":
        _admin_state.pop(uid, None)
        from database import set_force_join_config
        set_force_join_config("channel_link", msg.text.strip())
        await msg.reply_text(f"{E.SUCCESS} Channel link updated.", parse_mode="HTML")
        return


# ─────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────

def register_admin(app):
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(admin_panel_callbacks, pattern=r"^(admin_|menu_admin)"))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.Document.ALL | filters.PHOTO) & filters.ChatType.PRIVATE,
        admin_message_handler
    ))
