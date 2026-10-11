import json
import sqlite3
from pathlib import Path

from .util import now


class Database:
    def __init__(self, root):
        self.db = sqlite3.connect(Path(root)/"experiments.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS rounds (
            round INTEGER PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL,
            record TEXT, zip_sha256 TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS candidates (
            round INTEGER NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
            config TEXT NOT NULL, path TEXT NOT NULL, evaluation TEXT, error TEXT,
            PRIMARY KEY(round,label));
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
        ''')

    def event(self, kind, detail):
        with self.db:
            self.db.execute("INSERT INTO events(time,kind,detail) VALUES(?,?,?)",(now(),kind,json.dumps(detail)))

    def round_status(self, number, status, record=None, checksum=None, error=None):
        with self.db:
            self.db.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?) ON CONFLICT(round) DO UPDATE SET "
                "status=excluded.status,updated_at=excluded.updated_at,record=COALESCE(excluded.record,record),"
                "zip_sha256=COALESCE(excluded.zip_sha256,zip_sha256),error=excluded.error",
                (number,status,now(),json.dumps(record) if record else None,checksum,error))

    def candidate(self, number, label, status, config, path, evaluation=None, error=None):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?,?,?)",
                (number,label,status,json.dumps(config),str(path),json.dumps(evaluation) if evaluation else None,error))

    def reconcile(self, files, store):
        """ZIP index is authoritative after a crash between publication and SQLite commit."""
        from .util import digest
        history = json.loads(files["experiments/experiment-index.json"])
        number = len(history)
        # A corrupt newer snapshot must not remain falsely completed in the dashboard.
        with self.db:
            self.db.execute("UPDATE rounds SET status='recovery_required' WHERE round>? AND status='completed'",(number,))
        for record in history:
            archive = store.archive_path(record["round"])
            self.round_status(record["round"],"completed",record,digest(archive) if archive.exists() else None)
