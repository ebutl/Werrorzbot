"""database.py — SQLite + first_time welcome + payment proof + load balancer nodes"""

import sqlite3, json, logging, os, random, traceback, time, shutil, gzip
import tempfile
from datetime import datetime

sqlite3.register_adapter(datetime, lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"))
sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_THIS_DIR, "bot.db")
DEFAULT_CREDITS = 250


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception: pass
    return c


class _FakeConn:
    def __init__(self): self._c = _conn()
    def cursor(self): return self._c.cursor()
    def commit(self): self._c.commit()
    def rollback(self): self._c.rollback()
    def close(self):
        try: self._c.close()
        except: pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close(); return False


class _FakePool:
    def getconn(self): return _FakeConn()
    def putconn(self, c):
        try: c.close()
        except: pass
    def closeall(self): pass


connection_pool = _FakePool()


def create_connection_pool():
    try:
        c = _conn(); c.close()
        logger.info(f"✅ SQLite: {DB_PATH}")
        return True
    except Exception as e:
        logger.error(f"❌ SQLite: {e}")
        return False


def close_connection_pool(): pass


def _auto_migrate(c):
    try:
        cur = c.execute("PRAGMA table_info(users)")
        cols = [row["name"] for row in cur.fetchall()]
        if not cols: return
        for col, t in [
            ("user_id", "INTEGER PRIMARY KEY"),
            ("username", "TEXT"),
            ("joined_at", "TIMESTAMP"),
            ("tier", "TEXT DEFAULT 'Trial'"),
            ("credits", "INTEGER DEFAULT 250"),
            ("first_time_welcomed", "INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {t}"); c.commit()
                except: pass
    except: pass


def setup_database():
    c = _conn()
    try:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tier TEXT DEFAULT 'Trial', credits INTEGER DEFAULT 250,
                first_time_welcomed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS user_plans (
                user_id INTEGER PRIMARY KEY, tier TEXT NOT NULL, expiry_date TIMESTAMP);
            CREATE TABLE IF NOT EXISTS redeem_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL, duration_days INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP, used_by INTEGER);
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reason TEXT);
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS sites (
                url TEXT PRIMARY KEY, gateway TEXT DEFAULT '',
                price REAL DEFAULT 0, status TEXT DEFAULT 'Unknown',
                added_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                proxy TEXT NOT NULL, status TEXT DEFAULT 'unknown',
                response_time REAL DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, proxy));
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS check_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, status TEXT, gateway TEXT, card TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS payment_proofs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                key_code TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending');
            CREATE TABLE IF NOT EXISTS load_balancers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                provider TEXT DEFAULT 'vps',
                enabled INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS force_join_config (
                key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS broadcast_config (
                key TEXT PRIMARY KEY, value TEXT);
        """)
        c.commit()
        logger.info("✅ Tables ready")
        _auto_migrate(c)
        try:
            c.execute("INSERT OR REPLACE INTO users (user_id, username, joined_at, tier, credits) VALUES (?, ?, ?, ?, ?)",
                      (99999999999, "_test_", datetime.now(), "Trial", 999))
            c.commit()
            cur = c.execute("SELECT user_id FROM users WHERE user_id = ?", (99999999999,))
            if cur.fetchone():
                logger.info("✅ Write test PASSED")
                c.execute("DELETE FROM users WHERE user_id = ?", (99999999999,))
                c.commit()
        except Exception as e:
            logger.error(f"Write test failed: {e}")
    except Exception as e:
        logger.error(f"setup_database: {e}", exc_info=True)
    finally:
        c.close()


# ───────────────────────── USERS ─────────────────────────

def get_or_create_user(user_id, username=None):
    c = _conn()
    try:
        cur = c.execute("SELECT user_id, username, joined_at, tier, credits FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            if username and row["username"] != username:
                c.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
                c.commit()
            return (row["user_id"], row["joined_at"], row["tier"], row["credits"])
        c.execute("INSERT INTO users (user_id, username, joined_at, tier, credits, first_time_welcomed) VALUES (?,?,?,?,?,0)",
                  (user_id, username, datetime.now(), "Trial", DEFAULT_CREDITS))
        c.commit()
        cur = c.execute("SELECT user_id, username, joined_at, tier, credits FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return (row["user_id"], row["joined_at"], row["tier"], row["credits"])
    except Exception as e:
        logger.error(f"get_or_create_user {user_id}: {e}")
        return None
    finally:
        c.close()


def is_first_time(user_id: int) -> bool:
    """Returns True if user has never been welcomed, marks as welcomed after check."""
    c = _conn()
    try:
        cur = c.execute("SELECT first_time_welcomed FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return False
        if row["first_time_welcomed"] == 0:
            c.execute("UPDATE users SET first_time_welcomed=1 WHERE user_id=?", (user_id,))
            c.commit()
            return True
        return False
    except Exception:
        return False
    finally:
        c.close()


def get_user_credits(user_id):
    c = _conn()
    try:
        cur = c.execute("SELECT credits, tier FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row: return 0
        tier = row["tier"] or "Trial"
        if tier in ("Root", "X"): return float("inf")
        return row["credits"] or 0
    except: return 0
    finally: c.close()


def is_db_admin(user_id):
    c = _conn()
    try:
        cur = c.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return cur.fetchone() is not None
    except: return False
    finally: c.close()


def is_user_banned(user_id):
    c = _conn()
    try:
        cur = c.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))
        return cur.fetchone() is not None
    except: return False
    finally: c.close()


def ban_user(user_id, reason=""):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO banned_users (user_id, reason) VALUES (?,?)", (user_id, reason))
        c.commit(); return True
    except: return False
    finally: c.close()


def unban_user(user_id):
    c = _conn()
    try:
        c.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
        c.commit(); return True
    except: return False
    finally: c.close()


def add_db_admin(user_id):
    c = _conn()
    try:
        c.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (user_id,))
        c.commit(); return True
    except: return False
    finally: c.close()


def remove_db_admin(user_id):
    c = _conn()
    try:
        c.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))
        c.commit(); return True
    except: return False
    finally: c.close()


def update_user_plan(user_id, tier, expiry_date):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO user_plans (user_id, tier, expiry_date) VALUES (?,?,?)",
                  (user_id, tier, expiry_date))
        c.execute("UPDATE users SET tier=? WHERE user_id=?", (tier, user_id))
        c.commit(); return True
    except Exception as e:
        logger.error(f"update_user_plan: {e}"); return False
    finally: c.close()


def has_user_active_plan(user_id):
    c = _conn()
    try:
        cur = c.execute("SELECT expiry_date FROM user_plans WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row: return False
        exp = row["expiry_date"]
        if isinstance(exp, str): exp = datetime.fromisoformat(exp)
        return exp > datetime.now()
    except: return False
    finally: c.close()


# ───────────────────────── STATS ─────────────────────────

def get_total_users():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except: return 0
    finally: c.close()


def get_total_premium():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM user_plans WHERE expiry_date > ?", (datetime.now(),)).fetchone()[0]
    except: return 0
    finally: c.close()


def get_total_banned():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0]
    except: return 0
    finally: c.close()


def get_total_admins():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM bot_admins").fetchone()[0]
    except: return 0
    finally: c.close()


def get_all_user_ids():
    c = _conn()
    try:
        rows = c.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]
    except: return []
    finally: c.close()


def get_all_active_plans():
    c = _conn()
    try:
        rows = c.execute("SELECT user_id, tier, expiry_date FROM user_plans WHERE expiry_date > ?",
                         (datetime.now(),)).fetchall()
        return [(r["user_id"], r["tier"], r["expiry_date"]) for r in rows]
    except: return []
    finally: c.close()


def get_all_banned_users():
    c = _conn()
    try:
        rows = c.execute("SELECT user_id, reason FROM banned_users").fetchall()
        return [(r["user_id"], r["reason"]) for r in rows]
    except: return []
    finally: c.close()


def get_all_admins():
    c = _conn()
    try:
        rows = c.execute("SELECT user_id FROM bot_admins").fetchall()
        return [r["user_id"] for r in rows]
    except: return []
    finally: c.close()


def get_daily_stats():
    c = _conn()
    try:
        today = datetime.now().date().isoformat()
        total = c.execute("SELECT COUNT(*) FROM check_history WHERE DATE(created_at)=?", (today,)).fetchone()[0]
        charged = c.execute("SELECT COUNT(*) FROM check_history WHERE status='charged' AND DATE(created_at)=?", (today,)).fetchone()[0]
        approved = c.execute("SELECT COUNT(*) FROM check_history WHERE status='approved' AND DATE(created_at)=?", (today,)).fetchone()[0]
        return {"total": total, "charged": charged, "approved": approved}
    except: return {"total": 0, "charged": 0, "approved": 0}
    finally: c.close()


def get_total_charges():
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM check_history WHERE status='charged'").fetchone()[0]
    except: return 0
    finally: c.close()


def get_user_all_time_stats(user_id):
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=?", (user_id,)).fetchone()[0]
        charged = c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=? AND status='charged'", (user_id,)).fetchone()[0]
        approved = c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=? AND status='approved'", (user_id,)).fetchone()[0]
        declined = c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=? AND status='declined'", (user_id,)).fetchone()[0]
        return {"total": total, "charged": charged, "approved": approved, "declined": declined}
    except: return {"total": 0, "charged": 0, "approved": 0, "declined": 0}
    finally: c.close()


def get_user_charge_rank(user_id):
    c = _conn()
    try:
        rows = c.execute("""
            SELECT user_id, COUNT(*) as cnt FROM check_history
            WHERE status='charged' GROUP BY user_id ORDER BY cnt DESC
        """).fetchall()
        for i, r in enumerate(rows, 1):
            if r["user_id"] == user_id: return i
        return 0
    except: return 0
    finally: c.close()


# ───────────────────────── SITES ─────────────────────────

def get_total_sites():
    c = _conn()
    try: return c.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
    except: return 0
    finally: c.close()


def get_all_working_sites():
    c = _conn()
    try:
        rows = c.execute("SELECT url FROM sites WHERE status='Working'").fetchall()
        return [r["url"] for r in rows]
    except: return []
    finally: c.close()


def get_total_user_proxies(user_id):
    c = _conn()
    try: return c.execute("SELECT COUNT(*) FROM proxies WHERE user_id=?", (user_id,)).fetchone()[0]
    except: return 0
    finally: c.close()


def get_total_user_active_proxies(user_id):
    c = _conn()
    try: return c.execute("SELECT COUNT(*) FROM proxies WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
    except: return 0
    finally: c.close()


def get_total_proxies():
    c = _conn()
    try: return c.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
    except: return 0
    finally: c.close()


# ───────────────────────── SETTINGS ─────────────────────────

def get_setting(key, default=None):
    c = _conn()
    try:
        row = c.execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    except: return default
    finally: c.close()


def set_setting(key, value):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?,?)", (key, str(value)))
        c.commit()
    except: pass
    finally: c.close()


def is_bot_locked():
    return get_setting("bot_locked", "0") == "1"


def get_msh_speed():
    try: return int(get_setting("msh_speed", "2"))
    except: return 2


def set_msh_speed(v):
    set_setting("msh_speed", str(v))


# ───────────────────────── KEYS ─────────────────────────

def save_redeem_code(code, tier, days):
    c = _conn()
    try:
        c.execute("INSERT INTO redeem_codes (code, tier, duration_days) VALUES (?,?,?)", (code, tier, days))
        c.commit(); return True
    except: return False
    finally: c.close()


def get_unclaimed_keys():
    c = _conn()
    try: return c.execute("SELECT COUNT(*) FROM redeem_codes WHERE used_by IS NULL").fetchone()[0]
    except: return 0
    finally: c.close()


def get_redeem_code(code):
    c = _conn()
    try:
        row = c.execute("SELECT * FROM redeem_codes WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None
    except: return None
    finally: c.close()


def use_redeem_code(code, user_id):
    c = _conn()
    try:
        c.execute("UPDATE redeem_codes SET used_at=?, used_by=? WHERE code=?",
                  (datetime.now(), user_id, code))
        c.commit(); return True
    except: return False
    finally: c.close()


# ───────────────────────── PAYMENT PROOFS ─────────────────────────

def save_payment_proof(user_id, file_id, key_code=None):
    c = _conn()
    try:
        c.execute("INSERT INTO payment_proofs (user_id, file_id, key_code) VALUES (?,?,?)",
                  (user_id, file_id, key_code))
        c.commit(); return True
    except: return False
    finally: c.close()


def get_pending_proofs():
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM payment_proofs WHERE status='pending' ORDER BY submitted_at DESC").fetchall()
        return [dict(r) for r in rows]
    except: return []
    finally: c.close()


def update_proof_status(proof_id, status):
    c = _conn()
    try:
        c.execute("UPDATE payment_proofs SET status=? WHERE id=?", (status, proof_id))
        c.commit()
    except: pass
    finally: c.close()


# ───────────────────────── LOAD BALANCERS ─────────────────────────

def get_all_load_balancers():
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM load_balancers ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    except: return []
    finally: c.close()


def add_load_balancer(name, url, provider="vps"):
    c = _conn()
    try:
        c.execute("INSERT INTO load_balancers (name, url, provider) VALUES (?,?,?)", (name, url, provider))
        c.commit(); return True
    except: return False
    finally: c.close()


def toggle_load_balancer(lb_id, enabled):
    c = _conn()
    try:
        c.execute("UPDATE load_balancers SET enabled=? WHERE id=?", (1 if enabled else 0, lb_id))
        c.commit(); return True
    except: return False
    finally: c.close()


def remove_load_balancer(lb_id):
    c = _conn()
    try:
        c.execute("DELETE FROM load_balancers WHERE id=?", (lb_id,))
        c.commit(); return True
    except: return False
    finally: c.close()


def get_active_load_balancers():
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM load_balancers WHERE enabled=1").fetchall()
        return [dict(r) for r in rows]
    except: return []
    finally: c.close()


# ───────────────────────── BACKUP / RESTORE ─────────────────────────

def backup_database():
    """Create gzip-compressed backup. Returns list of paths (split at 18MB)."""
    c = _conn()
    try:
        raw_path = os.path.join(_THIS_DIR, "backup_raw.db")
        if os.path.exists(raw_path):
            try: os.remove(raw_path)
            except: pass
        safe = raw_path.replace("'", "''")
        c.execute(f"VACUUM INTO '{safe}'")
        if not os.path.exists(raw_path):
            logger.error("Backup file not created"); return None
        size = os.path.getsize(raw_path)
        if size < 1024:
            logger.error(f"Backup too small: {size}"); return None

        # Compress
        gz_path = os.path.join(_THIS_DIR, "backup.db.gz")
        with open(raw_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(raw_path)

        gz_size = os.path.getsize(gz_path)
        SPLIT_SIZE = 18 * 1024 * 1024  # 18MB

        if gz_size <= SPLIT_SIZE:
            logger.info(f"✅ Backup: {gz_size/1024:.1f} KB")
            return [gz_path]

        # Split into parts
        parts = []
        part_num = 0
        with open(gz_path, "rb") as f:
            while True:
                chunk = f.read(SPLIT_SIZE)
                if not chunk: break
                part_path = os.path.join(_THIS_DIR, f"backup_part{part_num}.db.gz")
                with open(part_path, "wb") as pf:
                    pf.write(chunk)
                parts.append(part_path)
                part_num += 1
        os.remove(gz_path)
        logger.info(f"✅ Backup split into {len(parts)} parts")
        return parts

    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True); return None
    finally:
        c.close()


def restore_database(new_db_path):
    """Restore from raw .db file."""
    try:
        if not os.path.exists(new_db_path):
            return False, "Source file missing"
        size = os.path.getsize(new_db_path)
        if size < 1024:
            return False, f"File too small ({size} bytes)"
        try:
            test = sqlite3.connect(new_db_path, timeout=10)
            try:
                integrity = test.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    return False, f"Integrity check failed: {integrity[0] if integrity else 'unknown'}"
                has_users = test.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone()
                if not has_users:
                    return False, "Missing 'users' table — not a bot database"
            finally:
                test.close()
        except sqlite3.DatabaseError as e:
            return False, f"Invalid SQLite file: {e}"
        try:
            c = _conn()
            try: c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.commit()
            finally: c.close()
        except Exception as e:
            logger.warning(f"Pre-restore checkpoint warning: {e}")
        for ext in ["", "-wal", "-shm"]:
            p = DB_PATH + ext
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
        tmp = DB_PATH + ".restoring"
        shutil.copy2(new_db_path, tmp)
        os.replace(tmp, DB_PATH)
        try:
            verify = _conn()
            rows = verify.execute("SELECT COUNT(*) FROM users").fetchone()
            verify.close()
            logger.info(f"✅ Restore OK — {rows[0]} users")
            return True, f"Restore successful — {rows[0]} users loaded"
        except Exception as e:
            return False, f"Post-restore verify failed: {e}"
    except Exception as e:
        logger.error(f"restore_database: {e}", exc_info=True)
        return False, f"Restore failed: {e}"


# ───────────────────────── FORCE JOIN CONFIG ─────────────────────────

def get_force_join_config():
    c = _conn()
    try:
        rows = c.execute("SELECT key, value FROM force_join_config").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except: return {}
    finally: c.close()


def set_force_join_config(key, value):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO force_join_config (key, value) VALUES (?,?)", (key, value))
        c.commit()
    except: pass
    finally: c.close()
