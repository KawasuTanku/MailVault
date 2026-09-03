"""SQLite database layer for MailVault."""

import json
import sqlite3
from pathlib import Path
from typing import Optional


DB_PATH = Path.home() / ".local" / "share" / "mailvault" / "mailvault.db"


def get_db(path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    """Create schema. Idempotent."""
    c = conn or get_db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT NOT NULL,
            envelope_id TEXT NOT NULL,
            message_id TEXT UNIQUE,
            date TEXT,
            from_addr TEXT,
            from_name TEXT,
            to_addr TEXT,
            to_name TEXT,
            subject TEXT,
            body_text TEXT,
            headers_json TEXT NOT NULL,
            raw_rfc5322 BLOB,
            seen INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account, envelope_id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_account ON messages(account);
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
        CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);

        CREATE TABLE IF NOT EXISTS sync_state (
            account TEXT PRIMARY KEY,
            last_sync TEXT,
            last_page INTEGER DEFAULT 0,
            total_synced INTEGER DEFAULT 0,
            total_skipped INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            subject,
            body_text,
            from_addr,
            from_name,
            to_addr,
            to_name,
            content=messages,
            content_rowid=id
        );

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, subject, body_text, from_addr, from_name, to_addr, to_name)
            VALUES (new.id, new.subject, new.body_text, new.from_addr, new.from_name, new.to_addr, new.to_name);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, subject, body_text, from_addr, from_name, to_addr, to_name)
            VALUES ('delete', old.id, old.subject, old.body_text, old.from_addr, old.from_name, old.to_addr, old.to_name);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, subject, body_text, from_addr, from_name, to_addr, to_name)
            VALUES ('delete', old.id, old.subject, old.body_text, old.from_addr, old.from_name, old.to_addr, old.to_name);
            INSERT INTO messages_fts(rowid, subject, body_text, from_addr, from_name, to_addr, to_name)
            VALUES (new.id, new.subject, new.body_text, new.from_addr, new.from_name, new.to_addr, new.to_name);
        END;
    """)
    c.commit()


def insert_message(conn: sqlite3.Connection, msg: dict) -> int:
    """Insert or update a message. Returns row id."""
    headers_json = msg.get("headers_json", "{}")
    if isinstance(headers_json, dict):
        headers_json = json.dumps(headers_json, ensure_ascii=False)
    raw_blob = msg.get("raw_rfc5322")
    if isinstance(raw_blob, str):
        raw_blob = raw_blob.encode("utf-8", errors="replace")

    cursor = conn.execute("""
        INSERT INTO messages
            (account, envelope_id, message_id, date, from_addr, from_name,
             to_addr, to_name, subject, body_text, headers_json, raw_rfc5322, seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            envelope_id=excluded.envelope_id,
            subject=excluded.subject,
            body_text=excluded.body_text,
            headers_json=excluded.headers_json,
            raw_rfc5322=excluded.raw_rfc5322,
            seen=excluded.seen
        RETURNING id
    """, (
        msg["account"], msg["envelope_id"], msg.get("message_id"),
        msg.get("date"), msg.get("from_addr"), msg.get("from_name"),
        msg.get("to_addr"), msg.get("to_name"), msg.get("subject"),
        msg.get("body_text"), headers_json, raw_blob,
        msg.get("seen", 0),
    ))
    row_id = cursor.fetchone()[0]
    return row_id


def is_message_id_synced(conn: sqlite3.Connection, message_id: str) -> bool:
    """Check if a message is already synced by Message-ID."""
    if not message_id:
        return False
    row = conn.execute(
        "SELECT id FROM messages WHERE message_id = ?", (message_id,)
    ).fetchone()
    return row is not None


def search(conn: sqlite3.Connection, query: str, account: Optional[str] = None, limit: int = 20) -> list:
    """Full-text search across subject and body."""
    sql = """
        SELECT m.id, m.account, m.subject, m.from_name, m.from_addr,
               m.date, m.seen, snippet(messages_fts, 2, '[', ']', '...', 32) as snip
        FROM messages_fts fts
        JOIN messages m ON m.id = fts.rowid
        WHERE messages_fts MATCH ?
    """
    params: list = [query]
    if account:
        sql += " AND m.account = ?"
        params.append(account)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def stats(conn: sqlite3.Connection) -> dict:
    """Return basic stats."""
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    accounts = [row[0] for row in conn.execute("SELECT DISTINCT account FROM messages").fetchall()]
    per_account = {}
    for acc in accounts:
        per_account[acc] = conn.execute("SELECT COUNT(*) FROM messages WHERE account = ?", (acc,)).fetchone()[0]
    return {"total": total, "accounts": per_account}


def get_sync_state(conn: sqlite3.Connection, account: str) -> Optional[dict]:
    """Get sync state for an account."""
    row = conn.execute("SELECT * FROM sync_state WHERE account = ?", (account,)).fetchone()
    return dict(row) if row else None


def update_sync_state(conn: sqlite3.Connection, account: str, last_page: int, total_synced: int, total_skipped: int) -> None:
    """Update sync state after a successful sync."""
    conn.execute("""
        INSERT INTO sync_state (account, last_sync, last_page, total_synced, total_skipped, updated_at)
        VALUES (?, datetime('now'), ?, ?, ?, datetime('now'))
        ON CONFLICT(account) DO UPDATE SET
            last_sync=excluded.last_sync,
            last_page=excluded.last_page,
            total_synced=sync_state.total_synced + excluded.total_synced,
            total_skipped=sync_state.total_skipped + excluded.total_skipped,
            updated_at=excluded.updated_at
    """, (account, last_page, total_synced, total_skipped))