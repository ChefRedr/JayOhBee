"""SQLite persistence. This is the authoritative bot state.

Tables:
  jobs          — every job ever seen, keyed by its stable identity
  applications  — every application attempt (a job can have several)
  runs          — per-run metrics for observability
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jobbot.config import DB_PATH
from jobbot.models.job import Job, JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    identity        TEXT PRIMARY KEY,
    company         TEXT NOT NULL,
    external_id     TEXT,
    title           TEXT NOT NULL,
    location        TEXT,
    job_url         TEXT NOT NULL,
    apply_url       TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    discovered_at   TEXT NOT NULL,
    posted_at       TEXT,
    salary          TEXT,
    department      TEXT,
    status          TEXT NOT NULL DEFAULT 'discovered',
    status_reason   TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_identity    TEXT NOT NULL REFERENCES jobs(identity),
    attempted_at    TEXT NOT NULL,
    status          TEXT NOT NULL,
    reason          TEXT,
    application_url TEXT,
    evidence        TEXT,
    retryable       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    metrics_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_apps_job ON applications(job_identity);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DB_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- jobs

    def has_seen(self, identity: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE identity = ?", (identity,)).fetchone()
        return row is not None

    def record_job(self, job: Job, status: JobStatus, reason: str | None = None) -> None:
        """Insert a newly seen job. No-op if it already exists (dedup)."""
        self.conn.execute(
            """INSERT OR IGNORE INTO jobs
               (identity, company, external_id, title, location, job_url, apply_url,
                source_provider, discovered_at, posted_at, salary, department,
                status, status_reason, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.identity, job.company, job.external_id, job.title, job.location,
                job.job_url, job.apply_url, job.source_provider, job.discovered_at,
                job.posted_at, job.salary, job.department, str(status), reason, _now(),
            ),
        )
        self.conn.commit()

    def set_job_status(self, identity: str, status: JobStatus, reason: str | None = None) -> None:
        self.conn.execute(
            "UPDATE jobs SET status = ?, status_reason = ?, updated_at = ? WHERE identity = ?",
            (str(status), reason, _now(), identity),
        )
        self.conn.commit()

    def get_job(self, identity: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE identity = ?", (identity,)).fetchone()

    def jobs_with_status(self, *statuses: JobStatus) -> list[sqlite3.Row]:
        marks = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY discovered_at",
            [str(s) for s in statuses],
        ).fetchall()

    # ------------------------------------------------------- applications

    def record_application(
        self,
        job_identity: str,
        status: str,
        reason: str | None = None,
        application_url: str | None = None,
        evidence: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.conn.execute(
            """INSERT INTO applications
               (job_identity, attempted_at, status, reason, application_url, evidence, retryable)
               VALUES (?,?,?,?,?,?,?)""",
            (job_identity, _now(), status, reason, application_url, evidence, int(retryable)),
        )
        self.conn.commit()

    def application_attempts(self, job_identity: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE job_identity = ?", (job_identity,)
        ).fetchone()
        return row["n"]

    def has_completed_application(self, job_identity: str) -> bool:
        """Seen-vs-applied distinction: only a submitted application counts as done."""
        row = self.conn.execute(
            "SELECT 1 FROM applications WHERE job_identity = ? AND status = 'submitted'",
            (job_identity,),
        ).fetchone()
        return row is not None

    # --------------------------------------------------------------- runs

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, metrics_json: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, metrics_json = ? WHERE id = ?",
            (_now(), metrics_json, run_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------- status

    def counts_by_status(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}
