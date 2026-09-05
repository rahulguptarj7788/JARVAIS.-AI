import sqlite3
from datetime import datetime

DB_PATH = "jarvis_local.db"


def _configure_connection(conn):
    """WAL mode lets the main app process and the background service
    process read/write the same file concurrently without hitting
    'database is locked' as often; busy_timeout makes SQLite retry
    internally for a bit instead of failing immediately."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


class ChatDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _configure_connection(self.conn)
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS wake_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spoken_text TEXT,
            consumed INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        self.conn.commit()

    def save_message(self, role, content):
        try:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO chat_messages (role, content) VALUES (?, ?)", (role, content))
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # busy_timeout already retried internally; give up quietly

    def get_recent_messages(self, limit=20):
        cur = self.conn.cursor()
        cur.execute("SELECT role, content FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        return list(reversed(rows))

    def push_wake_event(self, spoken_text):
        """Called from the separate background-service process."""
        try:
            conn = sqlite3.connect(DB_PATH)
            _configure_connection(conn)
            conn.execute("INSERT INTO wake_events (spoken_text) VALUES (?)", (spoken_text,))
            conn.commit()
            conn.close()
        except sqlite3.OperationalError:
            pass

    def pop_pending_wake_event(self):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id, spoken_text FROM wake_events WHERE consumed = 0 ORDER BY id ASC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            event_id, text = row
            cur.execute("UPDATE wake_events SET consumed = 1 WHERE id = ?", (event_id,))
            self.conn.commit()
            return text
        except sqlite3.OperationalError:
            return None
