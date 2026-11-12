"""backup_scheduler.py — Daily backup at 00:00 IST, sent to dev as gz file(s)"""

import logging
import asyncio
import os
from datetime import datetime
import pytz

from config import DEV_ID, BOT_NAME, BACKUP_HOUR_UTC, BACKUP_MINUTE_UTC
from database import backup_database
from emojis import PremiumEmoji as E

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


async def send_backup(bot, chat_id: int, label: str = "Scheduled"):
    """Create and send backup to chat_id."""
    try:
        paths = backup_database()
        if not paths:
            await bot.send_message(chat_id=chat_id,
                text=f"{E.ERROR} <b>Backup Failed</b> — DB error.", parse_mode="HTML")
            return False

        now_ist = datetime.now(IST).strftime("%d/%m/%Y %H:%M")
        for i, path in enumerate(paths):
            size_kb = os.path.getsize(path) / 1024
            part_label = f"Part {i+1}/{len(paths)}" if len(paths) > 1 else ""
            caption = (
                f"<blockquote>💾 <b>Backup</b> {part_label}</blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.CALANDER} <b>Time</b> ➠ <code>{now_ist} IST</code>\n"
                f"{E.STATS} <b>Size</b> ➠ <code>{size_kb:.1f} KB</code>\n"
                f"{E.INFO} <b>Type</b> ➠ <code>{label}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{E.RIGHT} Restore: send .db file and use admin panel Restore."
            )
            with open(path, "rb") as f:
                await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=os.path.basename(path),
                    caption=caption,
                    parse_mode="HTML"
                )
            try: os.remove(path)
            except: pass

        return True
    except Exception as e:
        logger.error(f"send_backup: {e}", exc_info=True)
        try:
            await bot.send_message(chat_id=chat_id,
                text=f"{E.ERROR} <b>Backup error:</b> <code>{e}</code>", parse_mode="HTML")
        except: pass
        return False


async def backup_loop(app):
    """Runs forever, sends backup once daily at BACKUP_HOUR_UTC:BACKUP_MINUTE_UTC UTC."""
    logger.info(f"Backup scheduler started — fires at {BACKUP_HOUR_UTC:02d}:{BACKUP_MINUTE_UTC:02d} UTC daily")
    fired_today = False
    while True:
        try:
            now = datetime.utcnow()
            if now.hour == BACKUP_HOUR_UTC and now.minute == BACKUP_MINUTE_UTC:
                if not fired_today:
                    fired_today = True
                    logger.info("🔁 Daily backup firing...")
                    await send_backup(app.bot, DEV_ID, label="Daily Auto")
            else:
                fired_today = False
            await asyncio.sleep(55)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"backup_loop: {e}")
            await asyncio.sleep(60)
