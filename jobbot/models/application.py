from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApplicationStatus(StrEnum):
    SUBMITTED = "submitted"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ApplicationResult:
    status: ApplicationStatus
    reason: str | None = None
    application_url: str | None = None
    evidence: str | None = None
    retryable: bool = False
