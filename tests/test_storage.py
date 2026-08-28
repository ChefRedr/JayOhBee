import pytest

from jobbot.models.job import Job, JobStatus
from jobbot.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def make_job(external_id="j1"):
    return Job(company="X", external_id=external_id, title="SWE New Grad",
               job_url="https://x/1", apply_url="https://x/1/apply",
               source_provider="greenhouse")


def test_dedup_record_is_idempotent(db):
    job = make_job()
    assert not db.has_seen(job.identity)
    db.record_job(job, JobStatus.ELIGIBLE)
    assert db.has_seen(job.identity)
    db.set_job_status(job.identity, JobStatus.APPLIED)
    # recording again must not reset status
    db.record_job(job, JobStatus.DISCOVERED)
    assert db.get_job(job.identity)["status"] == "applied"


def test_seen_is_not_applied(db):
    job = make_job()
    db.record_job(job, JobStatus.ELIGIBLE)
    assert db.has_seen(job.identity)
    assert not db.has_completed_application(job.identity)
    db.record_application(job.identity, "failed", reason="timeout", retryable=True)
    assert not db.has_completed_application(job.identity)
    db.record_application(job.identity, "submitted", evidence="confirmation text")
    assert db.has_completed_application(job.identity)
    assert db.application_attempts(job.identity) == 2


def test_status_transitions(db):
    job = make_job()
    db.record_job(job, JobStatus.DISCOVERED)
    for status in (JobStatus.ELIGIBLE, JobStatus.APPLICATION_STARTED,
                   JobStatus.NEEDS_REVIEW, JobStatus.APPLIED):
        db.set_job_status(job.identity, status, "r")
        assert db.get_job(job.identity)["status"] == str(status)


def test_jobs_with_status(db):
    a, b = make_job("a"), make_job("b")
    db.record_job(a, JobStatus.ELIGIBLE)
    db.record_job(b, JobStatus.FILTERED_OUT)
    rows = db.jobs_with_status(JobStatus.ELIGIBLE)
    assert [r["identity"] for r in rows] == [a.identity]
