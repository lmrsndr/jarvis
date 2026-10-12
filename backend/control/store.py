"""Durable control-plane state. Separate tables preserve existing memories."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)

    def db(self):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=20000")
        return c

    def init(self):
        with self.db() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS control_events(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, message TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS control_settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS control_skills(id TEXT PRIMARY KEY, manifest TEXT, installed_at TEXT);
            CREATE TABLE IF NOT EXISTS control_preferences(id TEXT PRIMARY KEY, title TEXT, content TEXT, expires_at TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS control_jobs(id TEXT PRIMARY KEY, request_id TEXT UNIQUE, title TEXT, skill TEXT, args TEXT, priority INTEGER, status TEXT, run_at TEXT, report_at TEXT, interval_seconds INTEGER, attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 1, approved INTEGER DEFAULT 0, checkpoint TEXT DEFAULT '{}', result TEXT DEFAULT '{}', error TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS control_outbox(id TEXT PRIMARY KEY, subject TEXT, body TEXT, status TEXT, attempts INTEGER DEFAULT 0, due_at TEXT, error TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS control_questions(id TEXT PRIMARY KEY, question TEXT, answer TEXT DEFAULT '', created_at TEXT);
            CREATE INDEX IF NOT EXISTS control_job_queue ON control_jobs(status,run_at,priority);
            """)
            c.execute(
                "UPDATE control_jobs SET status='interrupted',error='Application restarted during execution. Review checkpoint before resuming.',updated_at=? WHERE status='running'",
                (now(),),
            )

    def event(self, kind, message, data=None):
        with self.db() as c:
            c.execute(
                "INSERT INTO control_events(at,kind,message,data) VALUES(?,?,?,?)",
                (now(), kind, message, json.dumps(data or {})),
            )

    def events(self):
        with self.db() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,at,kind,message FROM control_events ORDER BY id DESC LIMIT 80"
                )
            ]

    def setting(self, key, default=None):
        with self.db() as c:
            r = c.execute(
                "SELECT value FROM control_settings WHERE key=?", (key,)
            ).fetchone()
            return json.loads(r["value"]) if r else default

    def set_setting(self, key, value):
        with self.db() as c:
            c.execute(
                "INSERT INTO control_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def preferences(self):
        with self.db() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM control_preferences WHERE expires_at IS NULL OR expires_at>? ORDER BY updated_at DESC",
                    (now(),),
                )
            ]

    def preference(self, title, content, expires_at=None, preference_id=None):
        pid = preference_id or uuid4().hex
        with self.db() as c:
            c.execute(
                "INSERT INTO control_preferences VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,expires_at=excluded.expires_at,updated_at=excluded.updated_at",
                (pid, title, content, expires_at, now()),
            )
        self.event("memory", "Preference saved: " + title)
        return pid

    def skills(self):
        with self.db() as c:
            return [
                json.loads(r["manifest"])
                for r in c.execute("SELECT manifest FROM control_skills ORDER BY id")
            ]

    def install(self, manifest):
        with self.db() as c:
            c.execute(
                "INSERT INTO control_skills VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET manifest=excluded.manifest,installed_at=excluded.installed_at",
                (manifest["id"], json.dumps(manifest), now()),
            )
        self.event("skill", "Owner installed " + manifest["name"])

    def jobs(self):
        with self.db() as c:
            return [
                self.decode(r)
                for r in c.execute(
                    "SELECT * FROM control_jobs ORDER BY created_at DESC LIMIT 200"
                )
            ]

    def job(self, jid):
        with self.db() as c:
            r = c.execute("SELECT * FROM control_jobs WHERE id=?", (jid,)).fetchone()
            return self.decode(r) if r else None

    @staticmethod
    def decode(row):
        d = dict(row)
        for key in ("args", "checkpoint", "result"):
            d[key] = json.loads(d[key])
        return d

    def enqueue(
        self,
        title,
        skill,
        args,
        priority=5,
        run_at=None,
        report_at=None,
        interval_seconds=0,
        request_id=None,
        approved=False,
        max_attempts=1,
    ):
        jid = uuid4().hex
        with self.db() as c:
            c.execute(
                "INSERT OR IGNORE INTO control_jobs(id,request_id,title,skill,args,priority,status,run_at,report_at,interval_seconds,max_attempts,approved,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    jid,
                    request_id or uuid4().hex,
                    title,
                    skill,
                    json.dumps(args),
                    priority,
                    "queued" if approved else "awaiting_approval",
                    run_at or now(),
                    report_at,
                    interval_seconds,
                    max_attempts,
                    int(approved),
                    now(),
                    now(),
                ),
            )
            if c.total_changes == 0:
                return self.decode(
                    c.execute(
                        "SELECT * FROM control_jobs WHERE request_id=?", (request_id,)
                    ).fetchone()
                )
        self.event(
            "job",
            title + " " + ("queued" if approved else "requires approval"),
            {"job_id": jid},
        )
        return self.job(jid)

    def update_job(self, jid, **values):
        allowed = {
            "priority",
            "status",
            "run_at",
            "report_at",
            "attempts",
            "approved",
            "checkpoint",
            "result",
            "error",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Unsupported job update")
        values["updated_at"] = now()
        for key in ("checkpoint", "result"):
            if key in values:
                values[key] = json.dumps(values[key])
        with self.db() as c:
            c.execute(
                "UPDATE control_jobs SET "
                + ",".join(k + "=?" for k in values)
                + " WHERE id=?",
                (*values.values(), jid),
            )
        return self.job(jid)

    def claim(self):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute(
                "SELECT * FROM control_jobs WHERE status='queued' AND approved=1 AND run_at<=? ORDER BY priority,run_at LIMIT 1",
                (now(),),
            ).fetchone()
            if not r:
                return None
            c.execute(
                "UPDATE control_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?",
                (now(), r["id"]),
            )
        return self.job(r["id"])

    def outbox(self, subject, body, due_at=None):
        with self.db() as c:
            c.execute(
                "INSERT INTO control_outbox(id,subject,body,status,due_at) VALUES(?,?,?,?,?)",
                (uuid4().hex, subject, body, "pending", due_at or now()),
            )

    def question(self, text):
        with self.db() as c:
            c.execute(
                "INSERT INTO control_questions(id,question,created_at) VALUES(?,?,?)",
                (uuid4().hex, text, now()),
            )

    def questions(self):
        with self.db() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM control_questions WHERE answer='' ORDER BY created_at DESC LIMIT 30"
                )
            ]
