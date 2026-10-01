"""Authentication foundation (Phase 1): users, password hashing, sessions.

Uses SQLite (standard library) and Werkzeug's password hashing (ships with Flask), so no
new dependencies. This is deliberately simple and self-contained.

⚠️ IMPORTANT — this is Phase 1 only. It gates the app behind a login, but the app is
still SINGLE-TENANT: settings and the trading loop are global. Do NOT let two real users
run trades until Phase 2 (per-user settings, per-user encrypted MT5 credentials, and a
per-user bot instance) is built, or they will overwrite each other. See SAAS_ROADMAP.md.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _ROOT / "users.db"
_SECRET_PATH = _ROOT / ".flask_secret"


def get_secret_key() -> str:
    """Load (or create + persist) the Flask session secret key."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip()
    secret = os.urandom(32).hex()
    _SECRET_PATH.write_text(secret)
    try:
        os.chmod(_SECRET_PATH, 0o600)
    except OSError:
        pass
    return secret


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


#: Per-user columns added on top of the base users table (name -> SQL type).
_EXTRA_COLUMNS = {
    "mt5_login": "TEXT",
    "mt5_password_enc": "TEXT",
    "mt5_server": "TEXT",
    "instrument": "TEXT",
    "telegram_chat_id": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 0",   # subscription on/off
    "expires_at": "TEXT",                     # subscription end date (ISO), optional
    "notes": "TEXT",
    "subdomain": "TEXT",                      # e.g. "jane" -> jane.yourbrand.com (when gating is on)
    "reset_code": "TEXT",                     # Telegram password-reset code
    "reset_expires": "TEXT",
}


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'user',
                created_at    TEXT NOT NULL
            )
            """
        )
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        for col, sqltype in _EXTRA_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {sqltype}")
        # Records which users have a LIVE trading loop that should be running. Used to
        # auto-resume trading after a server restart / VPS reboot.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS live_runs (
                email      TEXT PRIMARY KEY,
                dry_run    INTEGER NOT NULL DEFAULT 0,
                instrument TEXT,
                started_at TEXT NOT NULL
            )
            """
        )
        _init_trades(conn)


def _init_trades(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            mode       TEXT,
            instrument TEXT,
            side       TEXT,
            units      REAL,
            entry      REAL,
            exit       REAL,
            pnl        REAL,
            reason     TEXT,
            exit_reason TEXT,
            opened_at  TEXT,
            closed_at  TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_email ON trades(email)")


def add_trade(email: str, mode: str, t: dict) -> None:
    with _connect() as conn:
        _init_trades(conn)
        conn.execute(
            "INSERT INTO trades (email, mode, instrument, side, units, entry, exit, pnl, "
            "reason, exit_reason, opened_at, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (email, mode, t.get("instrument"), t.get("side"), t.get("units"),
             t.get("entry"), t.get("exit"), t.get("pnl"), t.get("reason"),
             t.get("exit_reason"), t.get("opened_at"), t.get("closed_at")),
        )


def list_trades(email: str, limit: int = 500) -> list:
    with _connect() as conn:
        _init_trades(conn)
        rows = conn.execute(
            "SELECT * FROM trades WHERE email = ? ORDER BY id DESC LIMIT ?",
            (email, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def trades_csv(email: str) -> str:
    import csv
    import io
    rows = list(reversed(list_trades(email, limit=100000)))  # oldest first for a statement
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["opened_at", "closed_at", "mode", "instrument", "side", "units",
                "entry", "exit", "pnl", "exit_reason", "reason"])
    for t in rows:
        w.writerow([t.get("opened_at"), t.get("closed_at"), t.get("mode"),
                    t.get("instrument"), t.get("side"), t.get("units"), t.get("entry"),
                    t.get("exit"), t.get("pnl"), t.get("exit_reason"), t.get("reason")])
    return buf.getvalue()


def set_live_run(email: str, dry_run: bool, instrument: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO live_runs (email, dry_run, instrument, started_at) "
            "VALUES (?,?,?,?)",
            (email, 1 if dry_run else 0, instrument,
             datetime.now(timezone.utc).isoformat()),
        )


def clear_live_run(email: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM live_runs WHERE email = ?", (email,))


def list_live_runs() -> list:
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM live_runs")]


# ── credential encryption (Fernet if available, else base64 with a warning) ──────
def _fernet():
    try:
        import base64
        import hashlib
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(get_secret_key().encode()).digest())
        return Fernet(key)
    except Exception:  # noqa: BLE001 — cryptography not installed
        return None


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    f = _fernet()
    if f is not None:
        return "enc:" + f.encrypt(plain.encode()).decode()
    import base64
    return "b64:" + base64.b64encode(plain.encode()).decode()


def decrypt_secret(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("enc:"):
        f = _fernet()
        return f.decrypt(stored[4:].encode()).decode() if f else ""
    if stored.startswith("b64:"):
        import base64
        return base64.b64decode(stored[4:]).decode()
    return stored


def secrets_are_strong() -> bool:
    """True if real encryption (cryptography/Fernet) is available."""
    return _fernet() is not None


# ── per-user provisioning (used by the admin CLI) ────────────────────────────────
def list_users() -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT email, role, active, expires_at, mt5_login, mt5_server, "
            "instrument, telegram_chat_id, subdomain, notes, created_at "
            "FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_settings(email: str):
    email = (email or "").strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["mt5_password"] = decrypt_secret(d.get("mt5_password_enc") or "")
    return d


def set_settings(email: str, **fields) -> bool:
    """Update per-user fields. Pass mt5_password (plaintext) to (re)encrypt it."""
    email = (email or "").strip().lower()
    if "mt5_password" in fields:
        fields["mt5_password_enc"] = encrypt_secret(fields.pop("mt5_password"))
    allowed = set(_EXTRA_COLUMNS) | {"mt5_password_enc", "role"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    cols = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        cur = conn.execute(f"UPDATE users SET {cols} WHERE email = ?",
                           (*updates.values(), email))
        return cur.rowcount > 0


def set_password(email: str, new_password: str) -> bool:
    email = (email or "").strip().lower()
    if len(new_password or "") < 8:
        return False
    with _connect() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                           (generate_password_hash(new_password), email))
        return cur.rowcount > 0


def start_reset(email: str):
    """Create a reset code for a user who has a Telegram chat id. Returns dict or None."""
    s = get_settings(email)
    if not s or not s.get("telegram_chat_id"):
        return None
    code = f"{int.from_bytes(os.urandom(4), 'big') % 1000000:06d}"
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    set_settings(email, reset_code=code, reset_expires=expires)
    return {"code": code, "chat_id": s["telegram_chat_id"]}


def complete_reset(email: str, code: str, new_password: str):
    """Verify a reset code and set the new password. Returns (ok, message)."""
    s = get_settings(email)
    if not s:
        return False, "No account with that email."
    stored = s.get("reset_code")
    if not stored or stored != (code or "").strip():
        return False, "That code is not correct."
    exp = s.get("reset_expires")
    try:
        if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
            return False, "That code has expired. Request a new one."
    except ValueError:
        pass
    if len(new_password or "") < 8:
        return False, "Password must be at least 8 characters."
    set_password(email, new_password)
    set_settings(email, reset_code="", reset_expires="")
    return True, "ok"


def is_active(email: str) -> bool:
    """True if the user's subscription is on and not past its expiry date."""
    s = get_settings(email)
    if not s or not s.get("active"):
        return False
    exp = s.get("expires_at")
    if exp:
        try:
            return datetime.fromisoformat(exp) >= datetime.now(timezone.utc)
        except ValueError:
            return True
    return True


def user_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def create_user(email: str, password: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        return False, "Please enter a valid email address."
    if len(password or "") < 8:
        return False, "Password must be at least 8 characters."
    # The very first account becomes the admin/owner.
    role = "admin" if user_count() == 0 else "user"
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
                (email, generate_password_hash(password), role,
                 datetime.now(timezone.utc).isoformat()),
            )
        return True, "created"
    except sqlite3.IntegrityError:
        return False, "An account with that email already exists."


def verify_user(email: str, password: str):
    email = (email or "").strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return {"id": row["id"], "email": row["email"], "role": row["role"]}
    return None
