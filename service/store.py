from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import Settings, defaults
from .content import CHAPTERS


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "audio").mkdir(exist_ok=True)
        (root / "documents").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "avatar.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, kb TEXT NOT NULL,
                digest TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, text TEXT NOT NULL,
                ordinal INTEGER NOT NULL, embedding TEXT, embedding_model TEXT);
            CREATE INDEX IF NOT EXISTS chunk_doc ON chunks(doc_id);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, session TEXT, kind TEXT NOT NULL,
                data TEXT NOT NULL);
        """)
        self.db.commit()
        if self.get("settings") is None:
            self.set("settings", defaults().model_dump())
        if self.get("chapters") is None:
            self.set("chapters", CHAPTERS)

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    @property
    def settings(self) -> Settings:
        return Settings.model_validate(self.get("settings"))

    def save_settings(self, settings: Settings):
        settings.validate_consistency()
        self.set("settings", settings.model_dump())

    def log(self, session: str, kind: str, data: dict):
        # Only callers' explicit event fields are stored. Never persist raw headers/audio.
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(at,session,kind,data) VALUES (?,?,?,?)",
                            (time.time(), session, kind, json.dumps(data, ensure_ascii=False)))
            self.db.execute("DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-2000 FROM events)")

    def events(self, limit=100):
        with self.lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def close(self):
        self.db.close()
