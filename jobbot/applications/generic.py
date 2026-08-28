"""Fallback adapter for providers without automated application support
(Ashby, Workday, iCIMS, custom sites): route straight to manual review."""
from __future__ import annotations

from jobbot.applications.base import ApplicationAdapter
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult, ApplicationStatus
from jobbot.models.job import Job


class GenericApplicationAdapter(ApplicationAdapter):
    provider = "generic"

    def apply(self, job: Job, profile: ApplicantProfile, dry_run: bool = True) -> ApplicationResult:
        return ApplicationResult(
            ApplicationStatus.NEEDS_REVIEW,
            reason=f"no automated application adapter for provider {job.source_provider!r}",
            application_url=job.apply_url or job.job_url,
        )
