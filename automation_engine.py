"""Durable core for a comment-triggered DM automation."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class PlatformClient(Protocol):
    def reply_to_comment(self, *, comment_id: str, text: str, idempotency_key: str) -> None: ...
    def send_dm(self, *, participant_id: str, text: str, idempotency_key: str) -> None: ...


@dataclass(frozen=True)
class Comment:
    event_id: str
    workspace_id: str
    platform: str
    comment_id: str
    participant_id: str
    text: str


@dataclass(frozen=True)
class Message:
    event_id: str
    workspace_id: str
    platform: str
    participant_id: str
    text: str


class AutomationService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: str = ":memory:") -> "AutomationService":
        # Keep transactions explicit via ``with self.db``. Autocommit would
        # break the inbox/run/outbox atomicity this service relies on.
        db = sqlite3.connect(path)
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(Path(__file__).with_name("schema.sql").read_text())
        return cls(db)

    def create_automation(self, *, automation_id: str, workspace_id: str, keyword: str,
                          reply_text: str, prompt_text: str, link_text: str,
                          platform: str = "instagram") -> None:
        self.db.execute("""INSERT INTO automations
            (id, workspace_id, version, platform, keyword, reply_text, prompt_text, link_text)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)""",
            (automation_id, workspace_id, platform, keyword.lower(), reply_text, prompt_text, link_text))

    def on_comment(self, event: Comment) -> bool:
        """Record a comment and start matching automation runs. Returns False if duplicate."""
        with self.db:
            if not self._accept_event(event.event_id, event.platform):
                return False
            automations = self.db.execute("""SELECT * FROM automations
                WHERE workspace_id=? AND platform=? AND enabled=1 AND keyword=?""",
                (event.workspace_id, event.platform, event.text.strip().lower())).fetchall()
            for automation in automations:
                run_id = new_id()
                self.db.execute("""INSERT INTO workflow_runs
                    (id, automation_id, automation_version, workspace_id, platform, participant_id, status, context_json)
                    VALUES (?, ?, ?, ?, ?, ?, 'waiting_for_email', ?)""",
                    (run_id, automation["id"], automation["version"], event.workspace_id,
                     event.platform, event.participant_id, json.dumps({"comment_id": event.comment_id})))
                self._enqueue(run_id, "reply_to_comment", {"comment_id": event.comment_id, "text": automation["reply_text"]})
                self._enqueue(run_id, "send_dm", {"participant_id": event.participant_id, "text": automation["prompt_text"]})
                try:
                    self.db.execute("""INSERT INTO waiters
                        (id, run_id, workspace_id, automation_id, platform, participant_id, kind)
                        VALUES (?, ?, ?, ?, ?, ?, 'email')""",
                        (new_id(), run_id, event.workspace_id, automation["id"], event.platform, event.participant_id))
                except sqlite3.IntegrityError:
                    # Another active trigger is already collecting this person's email.
                    self.db.execute("DELETE FROM workflow_runs WHERE id=?", (run_id,))
            return True

    def on_message(self, event: Message) -> bool:
        """Advance eligible email waits. Non-email messages are safely recorded then ignored."""
        with self.db:
            if not self._accept_event(event.event_id, event.platform):
                return False
            match = EMAIL.search(event.text)
            if not match:
                return True
            waiter = self.db.execute("""SELECT w.*, r.context_json, a.link_text FROM waiters w
                JOIN workflow_runs r ON r.id=w.run_id
                JOIN automations a ON a.id=r.automation_id
                WHERE w.workspace_id=? AND w.platform=? AND w.participant_id=?
                  AND w.kind='email' AND w.active=1 AND r.status='waiting_for_email'
                ORDER BY w.created_at LIMIT 1""",
                (event.workspace_id, event.platform, event.participant_id)).fetchone()
            if not waiter:
                return True
            self.db.execute("UPDATE waiters SET active=0 WHERE id=? AND active=1", (waiter["id"],))
            self.db.execute("UPDATE workflow_runs SET status='completed', completed_at=?, context_json=? WHERE id=?",
                (now(), json.dumps({**json.loads(waiter["context_json"]), "email": match.group(0)}), waiter["run_id"]))
            self._enqueue(waiter["run_id"], "send_dm", {"participant_id": event.participant_id, "text": waiter["link_text"]})
            return True

    def _accept_event(self, event_id: str, platform: str) -> bool:
        try:
            self.db.execute("INSERT INTO inbox_events(provider_event_id, platform) VALUES (?, ?)", (event_id, platform))
            return True
        except sqlite3.IntegrityError:
            return False

    def _enqueue(self, run_id: str, kind: str, payload: dict) -> None:
        row_id = new_id()
        self.db.execute("""INSERT INTO outbox(id, run_id, kind, payload_json, idempotency_key)
            VALUES (?, ?, ?, ?, ?)""", (row_id, run_id, kind, json.dumps(payload), f"outbox:{row_id}"))

    def dispatch_once(self, client: PlatformClient) -> bool:
        """Deliver one pending command. Production workers lease with SKIP LOCKED."""
        with self.db:
            row = self.db.execute("""SELECT * FROM outbox WHERE status='pending' AND available_at <= ?
                ORDER BY created_at LIMIT 1""", (now(),)).fetchone()
            if not row:
                return False
            claimed = self.db.execute("UPDATE outbox SET status='processing', attempts=attempts+1 WHERE id=? AND status='pending'", (row["id"],))
            if claimed.rowcount != 1:
                return False
        try:
            payload = json.loads(row["payload_json"])
            if row["kind"] == "reply_to_comment":
                client.reply_to_comment(comment_id=payload["comment_id"], text=payload["text"], idempotency_key=row["idempotency_key"])
            else:
                client.send_dm(participant_id=payload["participant_id"], text=payload["text"], idempotency_key=row["idempotency_key"])
        except Exception as exc:
            delay = min(2 ** row["attempts"], 3600)
            with self.db:
                self.db.execute("""UPDATE outbox SET status=CASE WHEN attempts >= 8 THEN 'dead' ELSE 'pending' END,
                    available_at=?, last_error=? WHERE id=?""",
                    ((datetime.now(UTC) + timedelta(seconds=delay)).isoformat(), str(exc), row["id"]))
            return False
        with self.db:
            self.db.execute("UPDATE outbox SET status='sent', sent_at=? WHERE id=?", (now(), row["id"]))
        return True

    def drain(self, client: PlatformClient) -> None:
        while self.dispatch_once(client):
            pass
