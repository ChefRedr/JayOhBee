"""Lever hosted application form (jobs.lever.co/{company}/{id}/apply).

Lever's programmatic apply endpoint needs employer API credentials, so a
personal bot uses the public hosted form instead.
"""
from __future__ import annotations

import logging

from jobbot.applications.base import ApplicationAdapter
from jobbot.applications.browser import fill_form, launch_page, save_debug_screenshot, visible_captcha
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult, ApplicationStatus
from jobbot.models.job import Job

log = logging.getLogger("jobbot.apply.lever")

CONFIRMATION_MARKERS = [
    "application submitted",
    "thank you for your interest",
    "your application has been received",
]


class LeverApplicationAdapter(ApplicationAdapter):
    provider = "lever"

    def apply(self, job: Job, profile: ApplicantProfile, dry_run: bool = True) -> ApplicationResult:
        clicked = False
        url = job.apply_url or f"{job.job_url.rstrip('/')}/apply"
        try:
            with launch_page() as page:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1500)

                report = fill_form(page, profile, form_selector="form#application-form, form")
                if report.blocked_reason:
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason=report.blocked_reason,
                        application_url=url,
                    )
                if report.unknown_required:
                    save_debug_screenshot(page, f"review_{job.company}_{job.external_id}")
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
                    "button#btn-submit, button[type='submit'], button:has-text('Submit application')"
                ).first
                if submit.count() == 0:
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason="submit button not found",
                        application_url=url,
                    )
                clicked = True  # from here on, submission state is unknown on error
                submit.click()
                page.wait_for_timeout(6000)

                if visible_captcha(page):
                    return ApplicationResult(
                        ApplicationStatus.NEEDS_REVIEW, reason="CAPTCHA challenge after submit",
                        application_url=url,
                    )
                body = page.inner_text("body").lower()
                if "/thanks" in page.url or any(m in body for m in CONFIRMATION_MARKERS):
                    return ApplicationResult(
                        ApplicationStatus.SUBMITTED, application_url=url,
                        evidence=f"confirmation at {page.url}",
                    )
                save_debug_screenshot(page, f"noconfirm_{job.company}_{job.external_id}")
                return ApplicationResult(
                    ApplicationStatus.NEEDS_REVIEW,
                    reason="submitted but no confirmation detected — verify manually",
                    application_url=url,
                )
        except Exception as exc:  # noqa: BLE001
            log.error("lever apply failed for %s: %s", url, exc)
            if clicked:
                # submit may have gone through — retrying could double-apply
                return ApplicationResult(
                    ApplicationStatus.NEEDS_REVIEW,
                    reason=f"error after submit was clicked ({type(exc).__name__}) — "
                           "submission state unknown, verify manually",
                    application_url=url,
                )
            return ApplicationResult(
                ApplicationStatus.FAILED, reason=f"{type(exc).__name__}: {exc}",
                application_url=url, retryable="Timeout" in type(exc).__name__,
            )
