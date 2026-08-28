"""Greenhouse hosted application form (boards.greenhouse.io /
job-boards.greenhouse.io). Fills the applicant-facing form with Playwright."""
from __future__ import annotations

import logging

from jobbot.applications.base import ApplicationAdapter
from jobbot.applications.browser import fill_form, launch_page, visible_captcha
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult, ApplicationStatus
from jobbot.models.job import Job

log = logging.getLogger("jobbot.apply.greenhouse")

CONFIRMATION_MARKERS = [
    "thank you for applying",
    "your application has been submitted",
    "application submitted",
    "we have received your application",
]


class GreenhouseApplicationAdapter(ApplicationAdapter):
    provider = "greenhouse"

    def apply(self, job: Job, profile: ApplicantProfile, dry_run: bool = True) -> ApplicationResult:
        url = job.apply_url or job.job_url
        try:
            with launch_page() as page:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                # hosted pages sometimes need the Apply button clicked to reveal the form
                for sel in ("#apply_button", "a[href='#app']", "button:has-text('Apply')"):
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click()
                        break
                page.wait_for_timeout(1500)

                report = fill_form(page, profile, form_selector="form")
                if report.blocked_reason:
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason=report.blocked_reason,
                        application_url=url,
                    )
                if report.unknown_required:
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW,
                        reason="unknown required fields: " + "; ".join(report.unknown_required[:6]),
                        application_url=url,
                    )
                if dry_run:
                    return ApplicationResult(
                        ApplicationStatus.SKIPPED,
                        reason=f"dry run — all {len(report.filled)} fields resolvable, would submit",
                        application_url=url,
                    )

                submit = page.locator(
                    "input[type='submit'], button[type='submit'], #submit_app, "
                    "button:has-text('Submit application'), button:has-text('Submit Application')"
                ).first
                if submit.count() == 0:
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason="submit button not found",
                        application_url=url,
                    )
                submit.click()
                page.wait_for_timeout(6000)

                if visible_captcha(page):
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason="CAPTCHA challenge after submit",
                        application_url=url,
                    )
                body = page.inner_text("body").lower()
                for marker in CONFIRMATION_MARKERS:
                    if marker in body:
                        return ApplicationResult(
                            ApplicationStatus.SUBMITTED,
                            application_url=url,
                            evidence=f"confirmation text: {marker!r}",
                        )
                return ApplicationResult(
                    ApplicationStatus.NEEDS_REVIEW,
                    reason="submitted but no confirmation detected — verify manually",
                    application_url=url,
                )
        except Exception as exc:  # noqa: BLE001
            log.error("greenhouse apply failed for %s: %s", url, exc)
            return ApplicationResult(
                ApplicationStatus.FAILED, reason=f"{type(exc).__name__}: {exc}",
                application_url=url, retryable="Timeout" in type(exc).__name__,
            )
