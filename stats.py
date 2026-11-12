"""stats.py — /bot, /stats, /me, /leaderboard, /top (Premium emojis everywhere)"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from database import (
    get_total_users, get_total_admins, get_total_premium,
    get_total_proxies, get_total_sites,
    get_user_charge_rank, get_user_all_time_stats,
    get_charge_leaderboard, get_total_charges, is_db_admin,
)
from emojis import PremiumEmoji as E
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME

logger = logging.getLogger(__name__)


async def bot_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID and not is_db_admin(user.id):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Admin only</b></blockquote>",
            parse_mode="HTML")
        return

    users = get_total_users()
    admins = get_total_admins()
    premium = get_total_premium()
    proxies = get_total_proxies()
    sites = get_total_sites()
    charges = get_total_charges()

    text = (
        f"<blockquote>{E.STATS} <b>Bot Statistics</b></blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.USERS} <b>Users</b> ➠ <code>{users}</code>\n"
        f"{E.STAR} <b>Premium</b> ➠ <code>{premium}</code>\n"
        f"{E.SHIELD} <b>Admins</b> ➠ <code>{admins}</code>\n"
        f"{E.FIRE} <b>Total Charges</b> ➠ <code>{charges}</code>\n\n"
        f"{E.GLOBE} <b>Proxies</b> ➠ <code>{proxies}</code>\n"
        f"{E.SITES} <b>Sites</b> ➠ <code>{sites}</code>\n\n"
        f"{E.DATABASE} <b>DB</b> ➠ {E.SUCCESS} Online\n"
        f"{E.HOME} <b>Bot</b> ➠ {E.SUCCESS} Running\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )
    await update.message.reply_text(text, parse_mode="HTML")
    logger.info(f"/bot -> {user.id}")


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    stats = get_user_all_time_stats(uid)
    rank = get_user_charge_rank(uid)

    text = (
        f"<blockquote>{E.USER} <b>Your Stats</b> {E.SPARKLE}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.CARD} <b>Total Checked</b> ➠ <code>{stats['total']:,}</code>\n"
        f"{E.FIRE} <b>Charged</b> ➠ <code>{stats['charged']:,}</code>\n"
        f"{E.APPROVED} <b>Approved</b> ➠ <code>{stats['approved']:,}</code>\n"
        f"{E.ERROR} <b>Declined</b> ➠ <code>{stats['declined']:,}</code>\n"
    )
    if rank > 0:
        text += f"{E.CROWN} <b>Rank</b> ➠ <code>#{rank}</code>\n"
    text += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaders = get_charge_leaderboard(10)
    total = get_total_charges()

    if not leaders:
        await update.message.reply_text(
            f"<blockquote>{E.REPORT} <b>Leaderboard</b></blockquote>\n\n"
            f"{E.INFO} <i>No charges recorded yet.</i>",
            parse_mode="HTML")
        return

    # ═══ Premium rank icons — hierarchical ═══
    # #1 = Crown (King)
    # #2-3 = Star (Elite)
    # #4-5 = Fire (Top tier)
    # #6-10 = User (Rest)
    rank_icons = [
        E.CROWN,   # 1
        E.STAR,    # 2
        E.STAR,    # 3
        E.FIRE,    # 4
        E.FIRE,    # 5
        E.USER,    # 6
        E.USER,    # 7
        E.USER,    # 8
        E.USER,    # 9
        E.USER,    # 10
    ]

    lines = ""
    for i, l in enumerate(leaders):
        rank_icon = rank_icons[i] if i < len(rank_icons) else E.USER
        uid = l.get("user_id")
        cnt = l.get("count", 0)
        name = l.get("username") or "User"
        lines += (
            f"{rank_icon} <b>#{i+1}</b> "
            f"<a href='tg://user?id={uid}'>{name}</a> ➠ "
            f"<code>{cnt}</code> {E.FIRE}\n"
        )

    text = (
        f"<blockquote>{E.FIRE} <b>Top 10 Hitters</b> {E.CROWN}</blockquote>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{lines}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.STATS} <b>Total Charges:</b> <code>{total}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


def register_stats(app):
    app.add_handler(CommandHandler("bot", bot_stats_command))
    app.add_handler(CommandHandler("stats", leaderboard_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("top", leaderboard_command))
    app.add_handler(CommandHandler("me", me_command))
    logger.info("✅ /stats registered")
