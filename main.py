"""main.py — 𒉼 𝔢 𝔯 𝔯 𝔬 𝔯 乙"""

import logging, os, sys, asyncio, time, html, traceback
from datetime import datetime
import pytz
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TimedOut, NetworkError
from concurrent.futures import ThreadPoolExecutor

from config import (OWNER_ID, BOT_NAME, DEV_ID,
    ANIME_FALLBACK, START_PHOTO, HIT_DETECTION_GROUP_ID, GC_LINK, UPDATES_LINK)
from emojis import PremiumEmoji as E
from anime_image import get_anime_image
from ui import primary, success, danger

from forcejoin import force_join, check_joined_callback
from broad import broad
from cmds import cmds_command, cmds_callback_handler
from credits import handle_credits_command
from database import (get_or_create_user, get_user_credits, is_db_admin,
    get_total_sites, get_all_working_sites, get_total_user_proxies,
    get_total_user_active_proxies, is_bot_locked, has_user_active_plan,
    create_connection_pool, setup_database, close_connection_pool, is_first_time)
from plans import (handle_plan1, handle_plan2, handle_plan3, handle_plan4,
    handle_rplan, handle_planall, handle_decreds, get_user_current_tier)
from redeem import (handle_gplan1, handle_gplan2, handle_gplan3, handle_gplan4,
    handle_gcodes, handle_claim)
from sh import handle_sh_command
from msh import (handle_msh_command, handle_msh_confirm_callback,
    handle_msh_stop_callback, active_mass_checks as msh_active_mass_checks)
from vbv import handle_vbv_command
from admin import register_admin, get_admin_dashboard_text, get_admin_keyboard
from genkey import register_genkey
from delkey import register_delkey
from admin_commands import register_admin_commands
from api_config import register_capi
from fb import register_fb
from sites import register_sites
from proxy import register_proxy
from gen import handle_gen_command
from gate import handle_gate_command
from status import status_command, register_status_handlers
from stop import register_stop
from speed import register_speed
from jio import register_jio
from jchk import register_jchk
from stats import register_stats
from profile import register_profile
from lock import register_lock_commands
from pay import register_pay
from mdev import register_mdev
from loadbalancer import register_lb
from backup_scheduler import backup_loop

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)
IST = pytz.timezone("Asia/Kolkata")


def fmt_indian(dt):
    if dt.tzinfo is None: dt = pytz.utc.localize(dt)
    return dt.astimezone(IST).strftime("%d/%m/%y %H:%M:%S")


async def safe_send(context, chat_id, text, parse_mode=None, reply_markup=None, retries=3):
    for a in range(retries):
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text,
                parse_mode=parse_mode, reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            if a < retries - 1: await asyncio.sleep(1); continue
            raise


async def safe_photo(context, chat_id, photo, caption=None, parse_mode=None, reply_markup=None, retries=3):
    for a in range(retries):
        try:
            return await context.bot.send_photo(chat_id=chat_id, photo=photo,
                caption=caption, parse_mode=parse_mode, reply_markup=reply_markup)
        except (TimedOut, NetworkError):
            if a < retries - 1: await asyncio.sleep(1); continue
            raise


async def safe_answer(query, text=None, show_alert=False, retries=3):
    for a in range(retries):
        try:
            return await query.answer(text=text, show_alert=show_alert)
        except (TimedOut, NetworkError):
            if a < retries - 1: await asyncio.sleep(0.5); continue
            raise


async def on_startup(app):
    logger.info(f"🚀 {BOT_NAME} Started")
    asyncio.create_task(backup_loop(app))


async def on_shutdown(app):
    logger.info("🛑 Shutdown")


async def edit_menu(q, text, kb):
    try:
        if q.message.photo or q.message.video or q.message.animation:
            await q.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await q.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb,
                                       disable_web_page_preview=True)
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.warning(f"edit_menu: {e}")


async def _fetch_profile_data(uid, un):
    try:
        dd = get_or_create_user(uid, un)
        if dd: return dd, None
        return None, "get_or_create_user returned None"
    except Exception as e:
        logger.error(f"❌ DB EXCEPTION for {uid}: {type(e).__name__}: {e}")
        return None, f"{type(e).__name__}: {str(e)[:200]}"


def _profile_caption(user, dd):
    uid = user.id
    db_u, db_j, db_t, db_c = dd
    c = get_user_credits(uid)
    cds = "Infinite😎" if c == float("inf") else str(db_c)
    fj = fmt_indian(db_j)
    du = f"@{html.escape(db_u)}" if db_u else "None"
    ef = html.escape(user.first_name or "User")

    try:
        real_tier = get_user_current_tier(uid)
    except Exception:
        real_tier = db_t or "Trial"

    return (f"<blockquote>{E.FIRE} <b>{BOT_NAME}</b> {E.SPARKLE}</blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.USER} <b>ID</b> ➠ <code>{uid}</code>\n"
            f"{E.EMOJI_3} <b>User</b> ➠ {du}\n"
            f"{E.EMOJI_2} <b>Name</b> ➠ <a href='tg://user?id={uid}'>{ef}</a> <code>[{html.escape(real_tier)}]</code>\n"
            f"{E.PREMIUM} <b>Credits</b> ➠ <code>{cds}</code>\n"
            f"{E.CALANDER} <b>Joined</b> ➠ <code>{fj}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")


def _profile_kb(user_id):
    from emojis import ButtonEmoji as BE
    is_admin = (user_id == OWNER_ID or is_db_admin(user_id))
    rows = [
        [primary("Gates",    "menu_gates",    icon=BE.GATES),
         danger( "Hitters",  "menu_hitters",  icon=BE.FIRE)],
        [primary("Tools",    "menu_tools",    icon=BE.SETTINGS_EMOJI),
         success("Commands", "menu_commands", icon=BE.SEARCH)],
        [success("Pricing",  "menu_pricing",  icon=BE.PRICING),
         success("Stats",    "menu_stats",    icon=BE.STATS_EMOJI)],
    ]
    if is_admin:
        rows.append([danger("Admin Panel", "menu_admin", icon=BE.ADMIN)])
    rows.append([primary("Group",   url=GC_LINK,      icon=BE.GROUP),
                 primary("Updates", url=UPDATES_LINK, icon=BE.UPDATES)])
    rows.append([danger("Close", "close_menu")])
    return InlineKeyboardMarkup(rows)


# ─────────────────────── FIRST TIME WELCOME ───────────────────────

WELCOME_MSG = (
    "• BOT IS STEALER LESS\n"
    "• SO IT'S PAID ONLY\n"
    "• FUCK HATER'S"
)

async def _send_first_time_welcome(context, chat_id):
    """Send welcome message once and pin it."""
    try:
        # Bold styled message
        text = (
            f"<blockquote>"
            f"<b>• BOT IS STEALER LESS</b>\n"
            f"<b>• SO IT'S PAID ONLY</b>\n"
            f"<b>• FUCK HATER'S</b>"
            f"</blockquote>"
        )
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML"
        )
        try:
            await context.bot.pin_chat_message(
                chat_id=chat_id,
                message_id=msg.message_id,
                disable_notification=True
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"first_time_welcome: {e}")


# ─────────────────────── START ───────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user    = update.effective_user
    uid     = user.id

    # Animated loading
    try:
        lm = await context.bot.send_message(chat_id=chat_id,
            text="<blockquote>▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱</blockquote>", parse_mode="HTML")
    except: lm = None
    for i in range(1, len(BOT_NAME) + 1):
        if lm is None: break
        try:
            await lm.edit_text(f"<blockquote><b>{BOT_NAME[:i]}</b></blockquote>", parse_mode="HTML")
            await asyncio.sleep(0.13)
        except: break
    for b in ["▰▱▱▱▱▱▱▱","▰▰▱▱▱▱▱▱","▰▰▰▱▱▱▱▱","▰▰▰▰▱▱▱▱",
              "▰▰▰▰▰▱▱▱","▰▰▰▰▰▰▱▱","▰▰▰▰▰▰▰▱","▰▰▰▰▰▰▰▰"]:
        if lm is None: break
        try:
            await lm.edit_text(f"<blockquote><b>{BOT_NAME}</b>\n{b}</blockquote>", parse_mode="HTML")
            await asyncio.sleep(0.09)
        except: break
    await asyncio.sleep(0.35)
    if lm is not None:
        try: await lm.delete()
        except: pass

    # First-time welcome (runs before profile)
    un = user.username if user.username else None
    get_or_create_user(uid, un)  # ensure user exists first
    if is_first_time(uid):
        await _send_first_time_welcome(context, chat_id)

    await start_sequence(chat_id, context, user)


async def start_sequence(chat_id, context, user):
    uid = user.id
    un  = user.username if user.username else None
    dd, err = await _fetch_profile_data(uid, un)
    if not dd:
        err_display = html.escape(str(err)[:300]) if err else "Unknown DB error"
        await safe_send(context, chat_id,
            f"<blockquote>{E.ERROR} <b>DB Error</b></blockquote>\n\n"
            f"{E.NOTE} <b>Error:</b>\n<code>{err_display}</code>\n\n"
            f"{E.INFO} <i>Copy and send to dev</i>\n"
            f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}",
            parse_mode=ParseMode.HTML)
        return
    caption = _profile_caption(user, dd)
    kb      = _profile_kb(uid)
    image_url = await get_anime_image()
    try:
        await safe_photo(context=context, chat_id=chat_id, photo=image_url,
            caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    except:
        try:
            await safe_photo(context=context, chat_id=chat_id, photo=ANIME_FALLBACK,
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        except:
            await safe_send(context, chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=kb)


async def render_profile(q, context):
    user = q.from_user
    uid  = user.id
    un   = user.username if user.username else None
    dd, err = await _fetch_profile_data(uid, un)
    if not dd:
        err_display = html.escape(str(err)[:200]) if err else "Unknown"
        await safe_answer(q, f"DB error: {err_display}", show_alert=True)
        return
    caption = _profile_caption(user, dd)
    kb      = _profile_kb(uid)
    await edit_menu(q, caption, kb)


async def handle_buttons(update, context):
    q    = update.callback_query
    data = q.data
    uid  = q.from_user.id
    await safe_answer(q)

    if data == "close_menu":
        try: await q.message.delete()
        except: pass
        return

    if data == "back_main":
        await render_profile(q, context); return

    if data == "menu_gates":
        text = (f"<blockquote>{E.THUNDER} <b>Gates</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.GATE} <b>/sh</b> ➠ Shopify Single\n"
                f"{E.GATE} <b>/msh</b> ➠ Shopify Mass\n"
                f"{E.GATE} <b>/vbv</b> ➠ Braintree 3DS2\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
        kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_hitters":
        has_access = (uid == OWNER_ID or is_db_admin(uid) or has_user_active_plan(uid))
        if not has_access:
            text = (f"<blockquote>{E.LOCK} <b>Hitters — Locked</b></blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Active plan required.</i>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.LINK} <b>Buy Plan</b> ➠ /pay")
        else:
            text = (f"<blockquote>{E.FIRE} <b>Hitters</b> {E.SPARKLE}</blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.THUNDER} <b>Jio Hitter</b>\n"
                    f"{E.RIGHT} <code>/jhit NUMBER AMOUNT CARD</code>\n\n"
                    f"<b>Example:</b>\n"
                    f"<code>/jhit 9999999999 19 4111111111111111|12|25|123</code>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
        kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_tools":
        is_owner_user = (uid == OWNER_ID)
        if is_owner_user:
            text = (f"<blockquote>{E.TOOLS} <b>Tools (Owner)</b></blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.SITES} <b>Sites</b> — global pool\n"
                    f"{E.GLOBE} <b>Proxies</b> — global pool\n"
                    f"{E.CARD} <code>/gen</code> — Card gen\n"
                    f"{E.SEARCH} <code>/gate</code> — Site scan\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
            kb = InlineKeyboardMarkup([
                [success("Sites","menu_sites_owner"), success("Proxies","menu_proxies_owner")],
                [primary("Back","back_main"), danger("Close","close_menu")],
            ])
        else:
            text = (f"<blockquote>{E.TOOLS} <b>Tools</b></blockquote>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.CARD} <code>/gen</code> — Card gen\n"
                    f"{E.SEARCH} <code>/gate</code> — Site scan\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
            kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_stats":
        from database import get_user_all_time_stats, get_user_charge_rank, get_total_charges
        stats  = get_user_all_time_stats(uid)
        rank   = get_user_charge_rank(uid)
        total  = get_total_charges()
        text = (f"<blockquote>{E.STATS} <b>Statistics</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.USER} <b>Your Stats</b>\n"
                f"{E.CARD} <b>Total Checked</b> ➠ <code>{stats['total']:,}</code>\n"
                f"{E.FIRE} <b>Charged</b> ➠ <code>{stats['charged']:,}</code>\n"
                f"{E.APPROVED} <b>Approved</b> ➠ <code>{stats['approved']:,}</code>\n"
                f"{E.ERROR} <b>Declined</b> ➠ <code>{stats['declined']:,}</code>\n")
        if rank > 0:
            text += f"{E.CROWN} <b>Rank</b> ➠ <code>#{rank}</code>\n"
        text += (f"━━━━━━━━━━━━━━━━━━\n"
                 f"{E.CARD} <b>Global Charges</b> ➠ <code>{total}</code>\n"
                 f"━━━━━━━━━━━━━━━━━━\n"
                 f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
        kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_sites_owner":
        if uid != OWNER_ID:
            await safe_answer(q, "Owner only", show_alert=True); return
        text = (f"<blockquote>{E.SITES} <b>Global Sites</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.STATS} <b>Total:</b> <code>{get_total_sites()}</code>\n"
                f"{E.APPROVED} <b>Working:</b> <code>{len(get_all_working_sites())}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.RIGHT} <code>/addsite URL</code>\n"
                f"{E.RIGHT} <code>/ts</code> — Test all\n"
                f"{E.RIGHT} <code>/getsite</code>\n"
                f"{E.RIGHT} <code>/rmsite URL</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
        kb = InlineKeyboardMarkup([[primary("Back","menu_tools")]])
        await edit_menu(q, text, kb); return

    if data == "menu_proxies_owner":
        if uid != OWNER_ID:
            await safe_answer(q, "Owner only", show_alert=True); return
        text = (f"<blockquote>{E.GLOBE} <b>Global Proxies</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.STATS} <b>Total:</b> <code>{get_total_user_proxies(OWNER_ID)}</code>\n"
                f"{E.APPROVED} <b>Active:</b> <code>{get_total_user_active_proxies(OWNER_ID)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.RIGHT} <code>/proxy</code> — Add\n"
                f"{E.RIGHT} <code>/tp</code> — Test all\n"
                f"{E.RIGHT} <code>/getproxy</code>\n"
                f"{E.RIGHT} <code>/rmproxy ID</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.LINK} <b>Dev</b> ➠ {BOT_NAME}")
        kb = InlineKeyboardMarkup([[primary("Back","menu_tools")]])
        await edit_menu(q, text, kb); return

    if data == "menu_commands":
        text = (f"<blockquote>{E.SEARCH} <b>Commands</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<b>Gates:</b> <code>/sh /msh /vbv</code>\n"
                f"<b>Tools:</b> <code>/gen /gate</code>\n"
                f"<b>Stats:</b> <code>/me /stats /top</code>\n"
                f"<b>Info:</b> <code>/credits /status /cmds /profile</code>\n"
                f"<b>Redeem:</b> <code>/claim CODE</code>\n"
                f"<b>Payment:</b> <code>/pay</code>\n"
                f"<b>Dev:</b> <code>/mdev MESSAGE</code>\n"
                f"<b>Stop:</b> <code>/stop SESSION_ID</code>\n"
                f"━━━━━━━━━━━━━━━━━━")
        kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_pricing":
        text = (f"<blockquote>{E.STAR} <b>Plans</b></blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.CALANDER} <b>7 Days</b> ➠ $8.00\n"
                f"{E.CALANDER} <b>15 Days</b> ➠ $14.00\n"
                f"{E.CALANDER} <b>30 Days</b> ➠ $25.00\n"
                f"{E.CALANDER} <b>90 Days</b> ➠ $60.00\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.APPROVED} <b>Unlimited credits</b>\n"
                f"{E.LINK} <b>Buy</b> ➠ /pay")
        kb = InlineKeyboardMarkup([[primary("Back","back_main"), danger("Close","close_menu")]])
        await edit_menu(q, text, kb); return

    if data == "menu_admin":
        if uid != OWNER_ID and not is_db_admin(uid):
            await safe_answer(q, "⛔ Admin only", show_alert=True); return
        try:
            text = get_admin_dashboard_text(uid)
            kb   = get_admin_keyboard(uid)
            await edit_menu(q, text, kb)
        except Exception as e:
            logger.error(f"admin panel: {e}")
            await safe_answer(q, "Error", show_alert=True)


def build_app():
    from dotenv import load_dotenv
    load_dotenv()
    TOKEN = os.getenv("BOT_TOKEN") or "8913376816:AAE0DPN2KQaSx73Jy99n1XpOZ2SIsk_lwVo"
    app = Application.builder().token(TOKEN).build()
    app.post_init     = on_startup
    app.post_shutdown = on_shutdown

    app.add_handler(CommandHandler("start", start))

    def _w(h):
        @force_join
        async def _f(update, context):
            if is_bot_locked():
                user = update.effective_user
                if user and user.id != OWNER_ID:
                    if update.callback_query:
                        await update.callback_query.answer("🔒 Bot is locked by Owner.", show_alert=True)
                    elif update.message:
                        await update.message.reply_text(
                            "🔒 <b>Bot is currently locked by Owner for maintenance.</b>",
                            parse_mode="HTML")
                    return
            return await h(update, context)
        return _f

    app.add_handler(CommandHandler("sh",   _w(handle_sh_command)))
    app.add_handler(CommandHandler("msh",  _w(handle_msh_command)))
    app.add_handler(CommandHandler("vbv",  _w(handle_vbv_command)))
    app.add_handler(CallbackQueryHandler(handle_msh_confirm_callback, pattern=r"^msh_(yes|no)_"))
    app.add_handler(CallbackQueryHandler(handle_msh_stop_callback,    pattern=r"^msh_stop_"))

    app.add_handler(CommandHandler("gen",    _w(handle_gen_command)))
    app.add_handler(CommandHandler("gate",   _w(handle_gate_command)))
    app.add_handler(CommandHandler("cmds",   _w(cmds_command)))
    app.add_handler(CommandHandler("credits",_w(handle_credits_command)))
    app.add_handler(CommandHandler("status", _w(status_command)))

    app.add_handler(CommandHandler("plan1",   _w(handle_plan1)))
    app.add_handler(CommandHandler("plan2",   _w(handle_plan2)))
    app.add_handler(CommandHandler("plan3",   _w(handle_plan3)))
    app.add_handler(CommandHandler("plan4",   _w(handle_plan4)))
    app.add_handler(CommandHandler("rplan",   _w(handle_rplan)))
    app.add_handler(CommandHandler("planall", _w(handle_planall)))
    app.add_handler(CommandHandler("decreds", _w(handle_decreds)))
    app.add_handler(CommandHandler("gplan1",  _w(handle_gplan1)))
    app.add_handler(CommandHandler("gplan2",  _w(handle_gplan2)))
    app.add_handler(CommandHandler("gplan3",  _w(handle_gplan3)))
    app.add_handler(CommandHandler("gplan4",  _w(handle_gplan4)))
    app.add_handler(CommandHandler("gcodes",  _w(handle_gcodes)))
    app.add_handler(CommandHandler("claim",   _w(handle_claim)))
    app.add_handler(CommandHandler("broad",   broad))

    register_lock_commands(app)
    register_admin(app)
    register_genkey(app)
    register_delkey(app)
    register_admin_commands(app)
    register_capi(app)
    register_fb(app)
    register_status_handlers(app)
    register_sites(app)
    register_proxy(app)
    register_speed(app)
    register_stats(app)
    register_profile(app)
    register_jio(app)
    register_jchk(app)
    register_stop(app)
    register_pay(app)
    register_mdev(app)
    register_lb(app)

    app.add_handler(CallbackQueryHandler(cmds_callback_handler,  pattern=r"^cmds_"))
    app.add_handler(CallbackQueryHandler(check_joined_callback,  pattern="check_joined"))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    return app


async def run_bot_async():
    app = build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logging.info(f"🚀 {BOT_NAME} polling!")
    stop = asyncio.Event()
    try: await stop.wait()
    except (KeyboardInterrupt, SystemExit): pass
    finally:
        logging.info("🛑 Shutdown...")
        for fn in [app.updater.stop, app.stop, app.shutdown]:
            try: await fn()
            except: pass


def main():
    global executor
    executor = ThreadPoolExecutor(max_workers=4)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("🔧 DB init...")
    if not create_connection_pool():
        logging.error("❌ DB failed"); sys.exit(1)
    setup_database()
    if os.getenv("PRECHECK") or "--check" in sys.argv:
        logging.info("✅ Pre-check passed"); close_connection_pool(); return
    logging.info(f"🚀 {BOT_NAME} Started")
    try: asyncio.run(run_bot_async())
    except KeyboardInterrupt: pass
    except Exception as e:
        logging.exception(f"❌ Fatal: {e}"); traceback.print_exc()
    finally:
        try: executor.shutdown(wait=False)
        except: pass
        close_connection_pool()


if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc(); sys.exit(1)
