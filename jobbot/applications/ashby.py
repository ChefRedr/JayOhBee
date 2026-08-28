"""Ashby hosted application form (jobs.ashbyhq.com/{org}/{job}/application).

Ashby's authenticated API is employer-side, so the personal bot fills the
public hosted form with Playwright. Forms are React-rendered; the resume
upload is a hidden input[type=file] behind a styled button (handled by
fill_form's file-input path).
"""
from __future__ import annotations

import logging

from jobbot.applications.base import ApplicationAdapter
from jobbot.applications.browser import (
    COVER_HINTS,
    RESUME_HINTS,
    FillReport,
    launch_page,
    save_debug_screenshot,
    visible_captcha,
)
from jobbot.applications.form_mapping import pick_option, resolve
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult, ApplicationStatus
from jobbot.models.job import Job

log = logging.getLogger("jobbot.apply.ashby")

CONFIRMATION_MARKERS = [
    "application submitted",
    "your application has been submitted",
    "thank you for applying",
    "we have received your application",
]


def _clean(label: str) -> str:
    import re

    return re.sub(r"[✱*]|\(required\)|required", "", label, flags=re.IGNORECASE).strip()


def fill_ashby_form(page, profile: ApplicantProfile) -> FillReport:
    """Ashby renders no <form>: each question lives in a `_fieldEntry`
    container, and yes/no questions are button groups. Same contract as
    fill_form — only explicitly known answers are used."""
    report = FillReport()
    if visible_captcha(page):
        report.blocked_reason = "CAPTCHA present"
        return report

    entries = page.locator("[class*='_fieldEntry']")
    if entries.count() == 0:
        report.blocked_reason = "no application form found on page"
        return report

    for i in range(entries.count()):
        entry = entries.nth(i)
        try:
            label_loc = entry.locator("label, [class*='label']").first
            raw_label = label_loc.inner_text().strip() if label_loc.count() else entry.inner_text()[:80]
            required = "✱" in raw_label or "*" in raw_label
            label = _clean(raw_label)

            file_input = entry.locator("input[type='file']")
            if file_input.count() > 0:
                low = label.lower()
                if any(h in low for h in RESUME_HINTS) and not any(h in low for h in COVER_HINTS):
                    file_input.first.set_input_files(str(profile.resume_path))
                    report.filled.append(f"resume upload ({label})")
                elif required:
                    report.unknown_required.append(f"required file: {label or 'unknown'}")
                continue

            select = entry.locator("select")
            if select.count() > 0:
                answer = resolve(label, profile)
                options = select.first.locator("option").all_inner_texts()
                if answer and (choice := pick_option(answer.value, options)):
                    select.first.select_option(label=choice)
                    report.filled.append(label)
                elif required:
                    report.unknown_required.append(f"select: {label or 'unknown'}")
                continue

            text_input = entry.locator("input:not([type='file']):not([type='hidden']), textarea")
            if text_input.count() > 0:
                el = text_input.first
                if el.input_value():
                    continue
                answer = resolve(label, profile)
                if answer:
                    el.fill(answer.value)
                    report.filled.append(label)
                elif required:
                    report.unknown_required.append(f"field: {label or 'unknown'}")
                continue

            # yes/no (or similar) button group
            buttons = entry.locator("button")
            texts = [t.strip() for t in buttons.all_inner_texts() if t.strip()]
            if texts:
                answer = resolve(label, profile)
                if answer and (choice := pick_option(answer.value, texts)):
                    buttons.nth(texts.index(choice)).click()
                    report.filled.append(label)
                elif required:
                    report.unknown_required.append(f"choice: {label or 'unknown'}")
                continue

            if required:
                report.unknown_required.append(f"unrecognized field: {label or 'unknown'}")
        except Exception as exc:  # noqa: BLE001 — unprocessable entries must not pass silently
            log.debug("ashby field %d error: %s", i, exc)
            report.unknown_required.append("unprocessable field")
    return report


class AshbyApplicationAdapter(ApplicationAdapter):
    provider = "ashby"

    def apply(self, job: Job, profile: ApplicantProfile, dry_run: bool = True) -> ApplicationResult:
        url = job.apply_url or f"{job.job_url.rstrip('/')}/application"
        try:
            with launch_page() as page:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3000)  # React render

                # if we landed on the description tab, switch to the form
                if page.locator("[class*='_fieldEntry']").count() == 0:
                    tab = page.locator("a:has-text('Application'), button:has-text('Apply')")
                    if tab.count() > 0 and tab.first.is_visible():
                        tab.first.click()
                        page.wait_for_timeout(1500)

                report = fill_ashby_form(page, profile)
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
                    "button:has-text('Submit Application'), button:has-text('Submit application'), "
                    "button[type='submit']"
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
                            ApplicationStatus.SUBMITTED, application_url=url,
                            evidence=f"confirmation text: {marker!r}",
                        )
                save_debug_screenshot(page, f"noconfirm_{job.company}_{job.external_id}")
                return ApplicationResult(
                    ApplicationStatus.NEEDS_REVIEW,
                    reason="submitted but no confirmation detected — verify manually",
                    application_url=url,
                )
        except Exception as exc:  # noqa: BLE001
            log.error("ashby apply failed for %s: %s", url, exc)
            return ApplicationResult(
                ApplicationStatus.FAILED, reason=f"{type(exc).__name__}: {exc}",
                application_url=url, retryable="Timeout" in type(exc).__name__,
            )
