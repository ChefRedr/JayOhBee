"""Application state-transition tests using a stubbed adapter (no browser)."""
import pytest

import jobbot.runner as runner
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationResult, ApplicationStatus
from jobbot.models.job import Job, JobStatus
from jobbot.storage.database import Database


class StubAdapter:
    provider = "stub"

    def __init__(self, result):
        self.result = result

    def apply(self, job, profile, dry_run=True):
        return self.result


class NullSheets:
    def upsert_job(self, **kwargs):
        pass


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    yield database
    database.close()


@pytest.fixture
def profile():
    return ApplicantProfile(first_name="T", last_name="A", email="t@e.com", phone="1")


def seed_job(db):
    job = Job(company="X", external_id="1", title="SWE New Grad",
              job_url="https://x/1", apply_url="https://x/1/apply",
              source_provider="greenhouse")
    db.record_job(job, JobStatus.ELIGIBLE)
    return job


def run_attempt(db, profile, result, identity, monkeypatch, dry_run=False):
    monkeypatch.setattr(runner, "get_adapter", lambda provider: StubAdapter(result))
    monkeypatch.setattr(runner.notifications, "send_email", lambda *a, **k: False)
    metrics = runner._metrics()
    runner.attempt_application(identity, db, NullSheets(), profile, metrics, dry_run)
    return metrics


def test_submitted_marks_applied(db, profile, monkeypatch):
    job = seed_job(db)
    result = ApplicationResult(ApplicationStatus.SUBMITTED, evidence="confirmation")
    metrics = run_attempt(db, profile, result, job.identity, monkeypatch)
    assert db.get_job(job.identity)["status"] == "applied"
    assert db.has_completed_application(job.identity)
    assert metrics["applications_succeeded"] == 1


def test_needs_review_marks_review(db, profile, monkeypatch):
    job = seed_job(db)
    result = ApplicationResult(ApplicationStatus.NEEDS_REVIEW, reason="unknown sponsorship question")
    metrics = run_attempt(db, profile, result, job.identity, monkeypatch)
    row = db.get_job(job.identity)
    assert row["status"] == "needs_review"
    assert "sponsorship" in row["status_reason"]
    assert not db.has_completed_application(job.identity)
    assert metrics["applications_needing_review"] == 1


def test_failed_job_stays_retryable(db, profile, monkeypatch):
    job = seed_job(db)
    result = ApplicationResult(ApplicationStatus.FAILED, reason="timeout", retryable=True)
    run_attempt(db, profile, result, job.identity, monkeypatch)
    assert db.get_job(job.identity)["status"] == "failed"
    # a later successful attempt still works (seen != done)
    ok = ApplicationResult(ApplicationStatus.SUBMITTED, evidence="confirmation")
    run_attempt(db, profile, ok, job.identity, monkeypatch)
    assert db.get_job(job.identity)["status"] == "applied"


def test_completed_application_never_reattempted(db, profile, monkeypatch):
    job = seed_job(db)
    ok = ApplicationResult(ApplicationStatus.SUBMITTED)
    run_attempt(db, profile, ok, job.identity, monkeypatch)
    metrics = run_attempt(db, profile, ok, job.identity, monkeypatch)
    assert metrics["applications_attempted"] == 0
    assert db.application_attempts(job.identity) == 1


def test_max_attempts_enforced(db, profile, monkeypatch):
    job = seed_job(db)
    fail = ApplicationResult(ApplicationStatus.FAILED, reason="boom", retryable=True)
    for _ in range(runner.MAX_APPLICATION_ATTEMPTS):
        run_attempt(db, profile, fail, job.identity, monkeypatch)
    metrics = run_attempt(db, profile, fail, job.identity, monkeypatch)
    assert metrics["applications_attempted"] == 0
    row = db.get_job(job.identity)
    assert row["status"] == "failed"
    assert "max application attempts" in row["status_reason"]


def test_dry_run_leaves_job_eligible(db, profile, monkeypatch):
    job = seed_job(db)
    skipped = ApplicationResult(ApplicationStatus.SKIPPED, reason="dry run")
    run_attempt(db, profile, skipped, job.identity, monkeypatch, dry_run=True)
    assert db.get_job(job.identity)["status"] == "eligible"
    assert not db.has_completed_application(job.identity)
