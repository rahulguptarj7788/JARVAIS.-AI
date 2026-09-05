import sqlite3
from datetime import datetime

DB_PATH = "jarvis_local.db"


class ChatDatabase:
    """Single SQLite file, shared between the main app process and the
    background wake-word service process (see services.py). Both open
    their own connection to the same file -- SQLite handles this safely
    as long as writes are short-lived (which they are here)."""

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
        cur = self.conn.cursor()
        cur.execute("INSERT INTO chat_messages (role, content) VALUES (?, ?)", (role, content))
        self.conn.commit()

    def get_recent_messages(self, limit=20):
        cur = self.conn.cursor()
        cur.execute("SELECT role, content FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        return list(reversed(rows))

    def push_wake_event(self, spoken_text):
        """Called by the background service (services.py) when it hears
        the hotword + a follow-up utterance."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO wake_events (spoken_text) VALUES (?)", (spoken_text,))
        conn.commit()
        conn.close()

    def pop_pending_wake_event(self):
        """Called by the main app's poll loop. Returns the oldest
        unconsumed wake event's text, or None."""
        cur = self.conn.cursor()
        cur.execute("SELECT id, spoken_text FROM wake_events WHERE consumed = 0 ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        event_id, text = row
        cur.execute("UPDATE wake_events SET consumed = 1 WHERE id = ?", (event_id,))
        self.conn.commit()
        return text 
