from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class JobStatus(StrEnum):
    DISCOVERED = "discovered"
    FILTERED_OUT = "filtered_out"
    ELIGIBLE = "eligible"
    APPLICATION_STARTED = "application_started"
    APPLIED = "applied"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CLOSED = "closed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    company: str
    external_id: str
    title: str
    job_url: str
    apply_url: str
    source_provider: str
    discovered_at: str = field(default_factory=_now_iso)
    location: str | None = None
    description: str | None = None
    posted_at: str | None = None
    salary: str | None = None
    department: str | None = None

    @property
    def identity(self) -> str:
        """Stable unique key: provider + company + external id.

        If the provider gave no external id, fall back to a hash of the
        stable descriptive fields.
        """
        if self.external_id:
            return f"{self.source_provider}:{self.company}:{self.external_id}"
        digest = hashlib.sha256(
            "|".join([
                self.company,
                self.title,
                self.location or "",
                self.job_url,
            ]).encode()
        ).hexdigest()[:16]
        return f"{self.source_provider}:{self.company}:hash:{digest}"
