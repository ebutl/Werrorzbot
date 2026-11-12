"""admin_commands.py — /auth /unauth /ban /unban /addadmin /rmadmin"""

import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database import (
    get_or_create_user, update_user_plan, is_user_banned,
    ban_user, unban_user, add_db_admin, remove_db_admin, is_db_admin,
)
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)


def _is_admin(uid):
    return uid == OWNER_ID or is_db_admin(uid)


def _is_owner(uid):
    return uid == OWNER_ID


async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text(
            f"<blockquote>{E.ERROR} <b>Admin only</b></blockquote>", parse_mode="HTML")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            f"<blockquote>{E.INFO} <b>Grant Plan</b></blockquote>\n\n"
            f"<b>Usage:</b> <code>/auth UID DAYS</code>\n"
            f"<b>Example:</b> <code>/auth 123456789 30</code>",
            parse_mode="HTML")
        return

    try:
        uid = int(context.args[0]); days = int(context.args[1])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid input.", parse_mode="HTML")
        return

    if days <= 0 or days > 365:
        await update.message.reply_text(f"{E.ERROR} Days must be 1-365.", parse_mode="HTML")
        return

    ud = get_or_create_user(uid, None)
    if not ud:
        await update.message.reply_text(f"{E.ERROR} User not found.", parse_mode="HTML")
        return

    # Auto pick tier
    if days >= 90: tier = "X"
    elif days >= 30: tier = "Root"
    elif days >= 15: tier = "Elite"
    else: tier = "Core"

    exp = datetime.now() + timedelta(days=days)
    if not update_user_plan(uid, tier, exp):
        await update.message.reply_text(f"{E.ERROR} DB fail.", parse_mode="HTML")
        return

    try:
        await context.bot.send_message(chat_id=uid,
            text=(f"<blockquote>{E.SUCCESS} <b>Plan Activated</b> {E.SPARKLE}</blockquote>\n"
                  f"{E.STAR} <b>Tier</b> ➠ <code>{tier}</code>\n"
                  f"{E.CLOCK} <b>Days</b> ➠ <code>{days}</code>\n"
                  f"{E.CALANDER} <b>Expires</b> ➠ <code>{exp.strftime('%d %b %Y %H:%M')}</code>"),
            parse_mode="HTML")
    except Exception:
        pass

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Granted</b></blockquote>\n"
        f"{E.USER} UID ➠ <code>{uid}</code>\n"
        f"{E.STAR} Tier ➠ <code>{tier}</code>\n"
        f"{E.CLOCK} Days ➠ <code>{days}</code>\n"
        f"{E.CALANDER} Expires ➠ <code>{exp.strftime('%d %b %Y %H:%M')}</code>",
        parse_mode="HTML")


async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/unauth UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return

    if not update_user_plan(uid, "Trial", None):
        await update.message.reply_text(f"{E.ERROR} Failed.", parse_mode="HTML")
        return

    try:
        await context.bot.send_message(chat_id=uid,
            text=f"<blockquote>{E.WARNING} <b>Plan Ended</b></blockquote>\n"
                 f"<i>Reverted to Trial.</i>", parse_mode="HTML")
    except Exception:
        pass

    await update.message.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Revoked</b></blockquote>\n"
        f"{E.USER} UID ➠ <code>{uid}</code>", parse_mode="HTML")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/ban UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return
    if uid == OWNER_ID:
        await update.message.reply_text(f"{E.WARNING} Can't ban owner.", parse_mode="HTML")
        return
    if is_user_banned(uid):
        await update.message.reply_text(f"{E.WARNING} Already banned.", parse_mode="HTML")
        return
    ban_user(uid)
    await update.message.reply_text(f"{E.SUCCESS} <code>{uid}</code> banned.", parse_mode="HTML")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/unban UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return
    if not unban_user(uid):
        await update.message.reply_text(f"{E.WARNING} Not banned.", parse_mode="HTML")
        return
    await update.message.reply_text(f"{E.SUCCESS} <code>{uid}</code> unbanned.", parse_mode="HTML")


async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text(f"{E.ERROR} Owner only.", parse_mode="HTML")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/addadmin UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return
    if is_db_admin(uid):
        await update.message.reply_text(f"{E.WARNING} Already admin.", parse_mode="HTML")
        return
    add_db_admin(uid)
    await update.message.reply_text(f"{E.SUCCESS} <code>{uid}</code> is now admin.", parse_mode="HTML")


async def rmadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_owner(user.id):
        await update.message.reply_text(f"{E.ERROR} Owner only.", parse_mode="HTML")
        return
    if len(context.args) != 1:
        await update.message.reply_text(f"{E.INFO} <code>/rmadmin UID</code>", parse_mode="HTML")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid.", parse_mode="HTML")
        return
    if uid == OWNER_ID:
        await update.message.reply_text(f"{E.WARNING} Can't remove owner.", parse_mode="HTML")
        return
    if not remove_db_admin(uid):
        await update.message.reply_text(f"{E.WARNING} Not admin.", parse_mode="HTML")
        return
    await update.message.reply_text(f"{E.SUCCESS} <code>{uid}</code> removed.", parse_mode="HTML")


def register_admin_commands(app: Application):
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("unauth", unauth))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("rmadmin", rmadmin))
    logger.info("✅ Admin commands registered")