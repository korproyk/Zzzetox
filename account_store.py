"""SQLite-backed accounts and per-user sleep data (cross-device sync)."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data"
TOKEN_TTL_DAYS = 90
GUEST_ACCOUNT_EMAIL = "__guest__@zzzetox.local"


def resolve_data_dir() -> Path:
    """Pick a writable directory for accounts.db (Render / local)."""
    candidates: list[Path] = []
    env_dir = os.environ.get("SLEEP_APP_DATA_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([ROOT / "data", Path("/var/data"), Path("/tmp/sleep_app_data")])
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    fallback = ROOT / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def is_guest_account_email(email: str) -> bool:
    return _normalize_email(email) == GUEST_ACCOUNT_EMAIL


class AccountStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        base = data_dir or resolve_data_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.data_dir = base
        self.db_path = base / "accounts.db"
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def count_users(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
                return int(row["c"]) if row else 0
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        email TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        age INTEGER,
                        country TEXT NOT NULL DEFAULT '',
                        password_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS auth_tokens (
                        token TEXT PRIMARY KEY,
                        email TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        FOREIGN KEY (email) REFERENCES users(email) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS sleep_data (
                        email TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (email) REFERENCES users(email) ON DELETE CASCADE
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _user_public(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "email": row["email"],
            "name": row["name"],
            "age": row["age"],
            "country": row["country"] or "",
            "createdAt": row["created_at"],
        }

    def get_user(self, email: str) -> dict[str, Any] | None:
        email = _normalize_email(email)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def create_user(
        self,
        *,
        email: str,
        name: str,
        age: int | None,
        country: str,
        password_hash: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        email = _normalize_email(email)
        if is_guest_account_email(email):
            raise ValueError("guest_account_reserved")
        created = created_at or _utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO users (email, name, age, country, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (email, name.strip(), age, country or "", password_hash, created),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                assert row is not None
                return self._user_public(row)
            except sqlite3.IntegrityError as exc:
                raise ValueError("email_already_registered") from exc
            finally:
                conn.close()

    def verify_login(self, email: str, password_hash: str) -> dict[str, Any] | None:
        email = _normalize_email(email)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if not row or row["password_hash"] != password_hash:
                    return None
                return self._user_public(row)
            finally:
                conn.close()

    def issue_token(self, email: str) -> str:
        email = _normalize_email(email)
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)).replace(microsecond=0)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM auth_tokens WHERE email = ?", (email,))
                conn.execute(
                    "INSERT INTO auth_tokens (token, email, expires_at) VALUES (?, ?, ?)",
                    (token, email, expires.isoformat()),
                )
                conn.commit()
                return token
            finally:
                conn.close()

    def resolve_token(self, token: str) -> str | None:
        token = str(token or "").strip()
        if not token:
            return None
        now = datetime.now(timezone.utc)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT email, expires_at FROM auth_tokens WHERE token = ?", (token,)
                ).fetchone()
                if not row:
                    return None
                expires = datetime.fromisoformat(row["expires_at"])
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < now:
                    conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
                    conn.commit()
                    return None
                return row["email"]
            finally:
                conn.close()

    def revoke_token(self, token: str) -> None:
        token = str(token or "").strip()
        if not token:
            return
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
                conn.commit()
            finally:
                conn.close()

    def get_sleep_bucket(self, email: str) -> dict[str, Any]:
        email = _normalize_email(email)
        default = {"activeStartAt": None, "history": [], "sleepGoalHours": None}
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload FROM sleep_data WHERE email = ?", (email,)
                ).fetchone()
                if not row:
                    return default
                data = json.loads(row["payload"])
                if not isinstance(data, dict):
                    return default
                if "history" not in data or not isinstance(data["history"], list):
                    data["history"] = []
                if "activeStartAt" not in data:
                    data["activeStartAt"] = None
                if "sleepGoalHours" not in data:
                    data["sleepGoalHours"] = None
                return data
            except (json.JSONDecodeError, TypeError):
                return default
            finally:
                conn.close()

    def list_ranking_participants(self) -> list[dict[str, Any]]:
        """Registered users with profile fields and sleep bucket for global rankings."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT u.email, u.name, u.age, u.country, s.payload
                    FROM users u
                    LEFT JOIN sleep_data s ON s.email = u.email
                    WHERE LOWER(u.email) != ?
                    ORDER BY u.created_at ASC
                    """,
                    (GUEST_ACCOUNT_EMAIL,),
                ).fetchall()
                out: list[dict[str, Any]] = []
                for row in rows:
                    bucket: dict[str, Any] = {"activeStartAt": None, "history": [], "sleepGoalHours": None}
                    if row["payload"]:
                        try:
                            data = json.loads(row["payload"])
                            if isinstance(data, dict):
                                bucket = data
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if "history" not in bucket or not isinstance(bucket["history"], list):
                        bucket["history"] = []
                    out.append(
                        {
                            "email": row["email"],
                            "name": row["name"],
                            "age": row["age"],
                            "country": row["country"] or "",
                            "bucket": bucket,
                        }
                    )
                return out
            finally:
                conn.close()

    def save_sleep_bucket(self, email: str, bucket: dict[str, Any]) -> None:
        email = _normalize_email(email)
        if is_guest_account_email(email):
            raise ValueError("guest_account_reserved")
        payload = json.dumps(bucket, ensure_ascii=False)
        updated = _utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO sleep_data (email, payload, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(email) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                    """,
                    (email, payload, updated),
                )
                conn.commit()
            finally:
                conn.close()


_store: AccountStore | None = None


def get_account_store() -> AccountStore:
    global _store
    if _store is None:
        _store = AccountStore()
    return _store
