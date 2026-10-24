"""Immutable, idempotent SQLite event ledger; projections are always rebuildable."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .types import FailureCase, FailureEvent, canonical, digest


class EventStore:
    def __init__(self, directory: str | Path, identity: dict):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ledger.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS artifacts (hash TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.append("run_identity", "identity", identity)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, event_id: str, kind: str, payload: dict) -> bool:
        body = canonical(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT kind, payload FROM records WHERE id=?", (event_id,)).fetchone()
            if old:
                if old != (kind, body):
                    raise ValueError(f"Event identity collision: {event_id}")
                return False
            db.execute("INSERT INTO records(id,kind,payload) VALUES(?,?,?)", (event_id, kind, body))
        return True

    def artifact(self, value: dict) -> str:
        body = canonical(value)
        key = digest(body)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO artifacts(hash,body) VALUES(?,?)", (key, body))
        return key

    def read_artifact(self, key: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT body FROM artifacts WHERE hash=?", (key,)).fetchone()
        if not row or digest(row[0]) != key:
            raise ValueError("Missing or corrupted evidence artifact")
        return json.loads(row[0])

    def get(self, event_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def records(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind=? ORDER BY seq", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def observe(self, event: FailureEvent) -> None:
        if event.source_split != "train" or event.outcome not in {"success", "failure"}:
            raise ValueError("Only valid training observations belong in the failure ledger")
        self.read_artifact(event.artifact_hash)
        self.append(event.event_id, "observation", asdict(event))

    def cases(self, skill_hash: str, *, before_step: int) -> list[FailureCase]:
        events = [r for r in self.records("observation") if r["step"] < before_step]
        groups: dict[tuple[str, str], list[dict]] = {}
        for event in events:
            if event["outcome"] == "failure":
                groups.setdefault((event["task_id"], event["failure_kind"]), []).append(event)
        cases = []
        for (task, signature), failures in groups.items():
            # A new version starts unverified. Success on an unadopted candidate
            # is never inserted into this observation stream by the runtime.
            relevant = [e for e in events if e["task_id"] == task and e["skill_hash"] == skill_hash
                        and (e["outcome"] == "success" or e["failure_kind"] == signature)]
            last = relevant[-1] if relevant else None
            was_resolved = any(e["task_id"] == task and e["outcome"] == "success" for e in events)
            state = "resolved_observed" if last and last["outcome"] == "success" else (
                "reopened" if last and was_resolved else "unresolved")
            cases.append(FailureCase(digest(canonical([task, signature])), task, signature, skill_hash, state,
                                     failures[0]["step"], failures[-1]["step"], len(failures),
                                     tuple(e["event_id"] for e in failures)))
        return cases
