"""Adapter registration + Ashby adapter behavior with a stubbed page (no network)."""
from unittest.mock import MagicMock, patch

import pytest

from jobbot.applications import get_adapter
from jobbot.applications.ashby import AshbyApplicationAdapter
from jobbot.applications.browser import FillReport
from jobbot.applications.generic import GenericApplicationAdapter
from jobbot.config import ApplicantProfile
from jobbot.models.application import ApplicationStatus
from jobbot.models.job import Job


def test_adapter_registration():
    assert get_adapter("greenhouse").provider == "greenhouse"
    assert get_adapter("lever").provider == "lever"
    assert get_adapter("ashby").provider == "ashby"
    # unsupported providers fall back to manual review
    assert isinstance(get_adapter("workday"), GenericApplicationAdapter)
    assert isinstance(get_adapter("smartrecruiters"), GenericApplicationAdapter)


def test_generic_adapter_routes_to_review():
    job = _job()
    result = GenericApplicationAdapter().apply(job, _profile(), dry_run=False)
    assert result.status == ApplicationStatus.NEEDS_REVIEW
    assert "no automated application adapter" in result.reason


def _job():
    return Job(company="X", external_id="1", title="SWE",
               job_url="https://jobs.ashbyhq.com/x/1",
               apply_url="https://jobs.ashbyhq.com/x/1/application",
               source_provider="ashby")


def _profile():
    return ApplicantProfile(first_name="T", last_name="A", email="t@e.com", phone="1")


@pytest.fixture
def fake_page():
    page = MagicMock()
    page.locator.return_value.count.return_value = 1
    page.locator.return_value.first.count.return_value = 1
    page.inner_text.return_value = ""
    with patch("jobbot.applications.ashby.launch_page") as lp, \
         patch("jobbot.applications.ashby.visible_captcha", return_value=False), \
         patch("jobbot.applications.ashby.save_debug_screenshot"):
        lp.return_value.__enter__.return_value = page
        yield page


def _apply(fill_report, dry_run, page):
    with patch("jobbot.applications.ashby.fill_ashby_form", return_value=fill_report):
        return AshbyApplicationAdapter().apply(_job(), _profile(), dry_run=dry_run)


def test_ashby_dry_run_skips(fake_page):
    result = _apply(FillReport(filled=["First Name"]), dry_run=True, page=fake_page)
    assert result.status == ApplicationStatus.SKIPPED
    assert "dry run" in result.reason


def test_ashby_unknown_required_needs_review(fake_page):
    report = FillReport(unknown_required=["field: Desired start date"])
    result = _apply(report, dry_run=False, page=fake_page)
    assert result.status == ApplicationStatus.NEEDS_REVIEW
    assert "Desired start date" in result.reason


def test_ashby_blocked_needs_review(fake_page):
    report = FillReport(blocked_reason="CAPTCHA present")
    result = _apply(report, dry_run=False, page=fake_page)
    assert result.status == ApplicationStatus.NEEDS_REVIEW
    assert result.reason == "CAPTCHA present"


def test_ashby_submitted_only_with_confirmation(fake_page):
    fake_page.inner_text.return_value = "Application submitted! We'll be in touch."
    result = _apply(FillReport(filled=["a"]), dry_run=False, page=fake_page)
    assert result.status == ApplicationStatus.SUBMITTED
    assert "confirmation" in result.evidence


def test_ashby_no_confirmation_needs_review(fake_page):
    fake_page.inner_text.return_value = "some unrelated page content"
    result = _apply(FillReport(filled=["a"]), dry_run=False, page=fake_page)
    assert result.status == ApplicationStatus.NEEDS_REVIEW
    assert "no confirmation" in result.reason


def test_ashby_exception_fails_retryable_on_timeout(fake_page):
    class TimeoutErrorFake(Exception):
        pass

    with patch("jobbot.applications.ashby.fill_ashby_form", side_effect=TimeoutErrorFake("slow")):
        result = AshbyApplicationAdapter().apply(_job(), _profile(), dry_run=False)
    assert result.status == ApplicationStatus.FAILED
    assert result.retryable


def test_ashby_post_click_exception_is_review_not_retryable(fake_page):
    # H1 regression: an error AFTER submit.click() must never be retried
    fake_page.inner_text.side_effect = RuntimeError("page vanished")
    result = _apply(FillReport(filled=["a"]), dry_run=False, page=fake_page)
    assert result.status == ApplicationStatus.NEEDS_REVIEW
    assert "submission state unknown" in result.reason
