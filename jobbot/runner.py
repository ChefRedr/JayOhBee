"""The recurring pipeline (Stage B): fetch -> filter -> dedupe -> apply -> log."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from jobbot.applications import get_adapter
from jobbot.config import (
    ApplicantProfile,
    auto_apply_enabled,
    env_flag,
    load_applicant,
    load_companies,
    load_filters,
)
from jobbot.filters.eligibility import evaluate
from jobbot.integrations import notifications
from jobbot.integrations.google_sheets import SheetsLog
from jobbot.models.application import ApplicationStatus
from jobbot.models.company import Company
from jobbot.models.job import Job, JobStatus
from jobbot.sources import get_source
from jobbot.sources.base import SourceError
from jobbot.storage.database import Database

log = logging.getLogger("jobbot.runner")

MAX_APPLICATION_ATTEMPTS = 3

_APP_TO_JOB_STATUS = {
    ApplicationStatus.SUBMITTED: JobStatus.APPLIED,
    ApplicationStatus.NEEDS_REVIEW: JobStatus.NEEDS_REVIEW,
    ApplicationStatus.FAILED: JobStatus.FAILED,
    ApplicationStatus.SKIPPED: JobStatus.ELIGIBLE,  # dry run leaves it eligible
}


def _metrics() -> dict:
    return {
        "companies_checked": 0,
        "companies_failed": 0,
        "jobs_seen": 0,
        "new_jobs": 0,
        "eligible_jobs": 0,
        "applications_attempted": 0,
        "applications_succeeded": 0,
        "applications_needing_review": 0,
        "applications_failed": 0,
        "runtime_seconds": 0,
    }


def process_company(company: Company, db: Database, sheets: SheetsLog,
                    filters, metrics: dict, record: bool = True) -> list[str]:
    """Fetch and record one company's jobs. Returns identities of new eligible jobs."""
    source = get_source(company.provider)
    if source is None:
        raise SourceError(f"no source adapter for provider {company.provider}")
    jobs = source.fetch_jobs(company)
    metrics["jobs_seen"] += len(jobs)
    debug_sheet = env_flag("SHEETS_DEBUG")

    new_eligible: list[str] = []
    for job in jobs:
        if db.has_seen(job.identity):
            continue
        metrics["new_jobs"] += 1
        decision = evaluate(job, filters)
        status = JobStatus.ELIGIBLE if decision.eligible else JobStatus.FILTERED_OUT
        if record:
            db.record_job(job, status, decision.reason)
        log.info("new job: %s | %s | %s -> %s (%s)",
                 company.name, job.title, job.location, status, decision.reason)
        if decision.eligible:
            metrics["eligible_jobs"] += 1
            new_eligible.append(job.identity)
            if record:
                sheets.upsert_job(
                    company=job.company, title=job.title, location=job.location,
                    date_found=job.discovered_at, job_url=job.job_url,
                    apply_url=job.apply_url, provider=job.source_provider,
                    status="Discovered",
                )
        elif debug_sheet and record:
            sheets.upsert_job(
                company=job.company, title=job.title, location=job.location,
                date_found=job.discovered_at, job_url=job.job_url,
                apply_url=job.apply_url, provider=job.source_provider,
                status="Filtered", notes=decision.reason,
            )
    return new_eligible


def _job_from_row(row) -> Job:
    return Job(
        company=row["company"], external_id=row["external_id"] or "",
        title=row["title"], location=row["location"], job_url=row["job_url"],
        apply_url=row["apply_url"], source_provider=row["source_provider"],
        discovered_at=row["discovered_at"],
    )


def attempt_application(identity: str, db: Database, sheets: SheetsLog,
                        profile: ApplicantProfile, metrics: dict, dry_run: bool) -> None:
    row = db.get_job(identity)
    if row is None:
        return
    if db.has_completed_application(identity):
        log.info("skip %s: already has a completed application", identity)
        return
    if db.application_attempts(identity) >= MAX_APPLICATION_ATTEMPTS:
        db.set_job_status(identity, JobStatus.FAILED, "max application attempts reached")
        return

    job = _job_from_row(row)
    metrics["applications_attempted"] += 1
    db.set_job_status(identity, JobStatus.APPLICATION_STARTED)
    adapter = get_adapter(job.source_provider)
    log.info("applying (%s, dry_run=%s): %s @ %s", adapter.provider, dry_run, job.title, job.company)
    result = adapter.apply(job, profile, dry_run=dry_run)

    db.record_application(
        identity, str(result.status), result.reason, result.application_url,
        result.evidence, result.retryable,
    )
    db.set_job_status(identity, _APP_TO_JOB_STATUS[result.status], result.reason)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if result.status == ApplicationStatus.SUBMITTED:
        metrics["applications_succeeded"] += 1
        sheets.upsert_job(
            company=job.company, title=job.title, location=job.location,
            date_found=job.discovered_at, job_url=job.job_url, apply_url=job.apply_url,
            provider=job.source_provider, status="Applied", applied_at=now,
            notes=result.evidence or "",
        )
        notifications.notify_applied(job.company, job.title, job.location, job.job_url)
    elif result.status == ApplicationStatus.NEEDS_REVIEW:
        metrics["applications_needing_review"] += 1
        sheets.upsert_job(
            company=job.company, title=job.title, location=job.location,
            date_found=job.discovered_at, job_url=job.job_url, apply_url=job.apply_url,
            provider=job.source_provider, status="Needs Review", needs_review="YES",
            notes=result.reason or "",
        )
        notifications.notify_needs_review(job.company, job.title, result.reason or "", job.job_url)
    elif result.status == ApplicationStatus.FAILED:
        metrics["applications_failed"] += 1
        sheets.upsert_job(
            company=job.company, title=job.title, location=job.location,
            date_found=job.discovered_at, job_url=job.job_url, apply_url=job.apply_url,
            provider=job.source_provider, status="Failed", notes=result.reason or "",
        )
    log.info("application result for %s: %s (%s)", identity, result.status, result.reason)


def run_pipeline(apply_stage: bool = True, record: bool = True,
                 company_slugs: list[str] | None = None) -> dict:
    """One full scheduled run. Failure in one company never aborts the rest."""
    start = time.monotonic()
    metrics = _metrics()
    companies = [c for c in load_companies() if c.is_runnable]
    if company_slugs:
        companies = [c for c in companies if c.slug in company_slugs]
    filters = load_filters()
    db = Database()
    sheets = SheetsLog()
    run_id = db.start_run() if record else None
    dry_run = not auto_apply_enabled()

    profile: ApplicantProfile | None = None
    if apply_stage:
        try:
            profile = load_applicant()
            problems = profile.validate()
            if problems:
                log.warning("applicant profile incomplete, skipping application stage: %s", problems)
                profile = None
        except FileNotFoundError as exc:
            log.warning("%s — skipping application stage", exc)

    all_new_eligible: list[str] = []
    for company in companies:
        metrics["companies_checked"] += 1
        try:
            new = process_company(company, db, sheets, filters, metrics, record=record)
            all_new_eligible.extend(new)
        except Exception as exc:  # noqa: BLE001 — failure isolation
            metrics["companies_failed"] += 1
            log.error("company failed: %s (%s): %s: %s",
                      company.name, company.provider, type(exc).__name__, exc)
        time.sleep(0.3)

    if apply_stage and profile is not None and record:
        for identity in all_new_eligible:
            try:
                attempt_application(identity, db, sheets, profile, metrics, dry_run)
            except Exception as exc:  # noqa: BLE001 — one application must not stop the rest
                metrics["applications_failed"] += 1
                log.error("application crashed for %s: %s: %s", identity, type(exc).__name__, exc)
            time.sleep(2)

    metrics["runtime_seconds"] = round(time.monotonic() - start, 1)
    if record and run_id is not None:
        db.finish_run(run_id, json.dumps(metrics))
    log.info("run complete: %s", json.dumps(metrics))
    if metrics["new_jobs"] or metrics["companies_failed"]:
        notifications.notify_summary(metrics)
    db.close()
    return metrics


def apply_pending(limit: int | None = None, include_failed: bool = False) -> dict:
    """Attempt applications for jobs still eligible (and optionally retryable failures)."""
    metrics = _metrics()
    db = Database()
    sheets = SheetsLog()
    dry_run = not auto_apply_enabled()
    try:
        profile = load_applicant()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return metrics
    problems = profile.validate()
    if problems:
        log.error("applicant profile invalid: %s", problems)
        return metrics

    # a run that died mid-attempt may have clicked submit already — never
    # auto-retry those, hand them to a human instead
    for row in db.jobs_with_status(JobStatus.APPLICATION_STARTED):
        db.set_job_status(
            row["identity"], JobStatus.NEEDS_REVIEW,
            "interrupted application attempt — submission state unknown, verify manually",
        )
        log.warning("flagged interrupted attempt for review: %s", row["identity"])

    statuses = [JobStatus.ELIGIBLE]
    if include_failed:
        statuses.append(JobStatus.FAILED)
    rows = db.jobs_with_status(*statuses)
    if limit:
        rows = rows[:limit]
    for row in rows:
        if row["status"] == str(JobStatus.FAILED) and not db.last_attempt_retryable(row["identity"]):
            continue
        try:
            attempt_application(row["identity"], db, sheets, profile, metrics, dry_run)
        except Exception as exc:  # noqa: BLE001
            metrics["applications_failed"] += 1
            log.error("application crashed for %s: %s", row["identity"], exc)
        time.sleep(2)
    db.close()
    log.info("apply pass complete: %s", json.dumps(metrics))
    return metrics
