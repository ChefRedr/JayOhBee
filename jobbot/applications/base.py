from __future__ import annotations

from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult
from jobbot.models.job import Job


class ApplicationAdapter:
    """Submits one application through an ATS's applicant-facing form.

    Contract:
      - fill only fields whose answers are explicitly known from the profile;
      - any unknown required field, CAPTCHA, or login wall returns
        needs_review — never guess;
      - only return SUBMITTED after observing provider-specific confirmation
        evidence, not merely after clicking submit.
    """

    provider: str = "generic"

    def apply(self, job: Job, profile: ApplicantProfile, dry_run: bool = True) -> ApplicationResult:
        raise NotImplementedError
