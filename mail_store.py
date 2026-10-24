"""Small local message store; each operation closes its SQLite connection."""

import sqlite3


def open_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        account TEXT, id TEXT, thread_id TEXT, timestamp INTEGER,
        sender TEXT, recipients TEXT, subject TEXT, body TEXT,
        PRIMARY KEY (account, id)
    )""")
    return db


def save(db, account, message):
    """Write within the caller's transaction; commit only after a complete fetch."""
    db.execute(
        "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (account, *(message[key] for key in (
            "id", "thread_id", "timestamp", "sender", "recipients", "subject", "body"
        ))),
    )


def messages(path, account):
    db = open_database(path)
    try:
        return db.execute(
            "SELECT id, timestamp, sender, subject FROM messages WHERE account = ? "
            "ORDER BY timestamp DESC, id", (account,),
        ).fetchall()
    finally:
        db.close()


def message(path, account, identifier):
    db = open_database(path)
    try:
        return db.execute(
            "SELECT * FROM messages WHERE account = ? AND id = ?", (account, identifier)
        ).fetchone()
    finally:
        db.close()
