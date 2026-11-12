"""pay.py — /pay command + payment proof upload handler"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

from config import OWNER_ID, BOT_NAME, DEV_ID
from database import save_payment_proof, get_pending_proofs, update_proof_status, is_db_admin
from emojis import PremiumEmoji as E
from ui import primary, success, danger

logger = logging.getLogger(__name__)

# Crypto payment details — edit as needed
CRYPTO_DETAILS = """
<blockquote>💎 <b>Payment Details</b></blockquote>
━━━━━━━━━━━━━━━━━━
{btc} <b>BTC</b>
<code>bc1qexampleaddresshere</code>

{sol} <b>SOL</b>
<code>SoLexampleaddresshere</code>

{bnb} <b>BNB (BEP-20)</b>
<code>0xexampleaddresshere</code>
━━━━━━━━━━━━━━━━━━
{plans}
<b>Plans:</b>
• 7 Days   ➠ $8
• 15 Days  ➠ $14
• 30 Days  ➠ $25
• 90 Days  ➠ $60
━━━━━━━━━━━━━━━━━━
{info} After payment, send screenshot + your Telegram ID here with /proof
"""

# Track users awaiting proof upload
_awaiting_proof: dict[int, bool] = {}


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = CRYPTO_DETAILS.format(
        btc=E.BITCOIN, sol=E.SOLANA, bnb=E.BINANCE,
        plans=E.STAR, info=E.INFO
    )
    kb = InlineKeyboardMarkup([
        [primary("Upload Proof", callback_data="pay_upload_proof")],
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if q.data == "pay_upload_proof":
        _awaiting_proof[uid] = True
        await q.message.reply_text(
            f"<blockquote>{E.FILE} <b>Upload Proof</b></blockquote>\n\n"
            f"Send your payment screenshot now.\n"
            f"Include your <b>Telegram ID</b>: <code>{uid}</code>\n\n"
            f"{E.INFO} <i>Also send the key/plan you paid for in the caption.</i>",
            parse_mode="HTML"
        )


async def proof_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if not _awaiting_proof.get(uid):
        return  # not awaiting, ignore

    _awaiting_proof.pop(uid, None)
    msg = update.message
    file_id = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
    else:
        return

    caption = msg.caption or ""
    # Extract key from caption if present
    key_code = None
    for word in caption.split():
        if "𒉼" in word or "-" in word and len(word) > 8:
            key_code = word.strip()
            break

    save_payment_proof(uid, file_id, key_code)

    await msg.reply_text(
        f"<blockquote>{E.SUCCESS} <b>Proof Received</b></blockquote>\n\n"
        f"{E.INFO} Your proof has been forwarded to admin.\n"
        f"You will be notified once verified.\n\n"
        f"{E.USER} <b>Your ID:</b> <code>{uid}</code>",
        parse_mode="HTML"
    )

    # Forward to dev silently
    try:
        caption_fwd = (
            f"🧾 <b>Payment Proof</b>\n"
            f"User: <code>{uid}</code> @{user.username or 'none'}\n"
            f"Key: <code>{key_code or 'not provided'}</code>"
        )
        if msg.photo:
            await context.bot.send_photo(chat_id=DEV_ID, photo=file_id, caption=caption_fwd, parse_mode="HTML")
        else:
            await context.bot.send_document(chat_id=DEV_ID, document=file_id, caption=caption_fwd, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Forward proof to dev: {e}")


def register_pay(app):
    app.add_handler(CommandHandler("pay", pay_command))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern=r"^pay_"))
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL) & filters.ChatType.PRIVATE,
        proof_photo_handler
    ))
