import pytest

from jobbot.config import load_filters
from jobbot.filters.eligibility import evaluate
from jobbot.models.job import Job


@pytest.fixture(scope="module")
def cfg():
    return load_filters()  # the real config/filters.yaml


def make_job(title, description="", location="San Francisco, CA"):
    return Job(company="X", external_id="1", title=title, job_url="u",
               apply_url="u", source_provider="greenhouse",
               description=description, location=location)


@pytest.mark.parametrize("title", [
    "Software Engineer, New Grad",
    "Software Engineer I",
    "Software Engineer 1 - Payments",
    "Associate Software Engineer",
    "Graduate Software Engineer",
    "Entry Level Software Developer",
    "Software Engineer, Early Career",
])
def test_positive_titles(cfg, title):
    assert evaluate(make_job(title), cfg).eligible


@pytest.mark.parametrize("title", [
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Principal Engineer",
    "Engineering Manager",
    "Director of Engineering",
    "Software Architect",
    "Sr. Software Engineer",
    "Lead Software Engineer",
])
def test_negative_titles(cfg, title):
    decision = evaluate(make_job(title), cfg)
    assert not decision.eligible


def test_internships_rejected(cfg):
    decision = evaluate(make_job("Software Engineering Intern (Summer 2027)"), cfg)
    assert not decision.eligible
    assert "intern" in decision.reason.lower()


def test_adjacent_title_needs_entry_marker(cfg):
    # bare adjacent title: rejected
    assert not evaluate(make_job("Backend Engineer"), cfg).eligible
    # adjacent + entry-level marker in description: accepted
    ok = make_job("Backend Engineer", description="Great for new grad engineers.")
    assert evaluate(ok, cfg).eligible


def test_excessive_experience_rejected(cfg):
    job = make_job("Software Engineer", description="You have 5+ years of experience with Java.")
    decision = evaluate(job, cfg)
    assert not decision.eligible
    assert "years" in decision.reason


def test_low_experience_accepted(cfg):
    job = make_job("Software Engineer I", description="0-1 years of experience required.")
    assert evaluate(job, cfg).eligible


def test_experience_range_uses_minimum(cfg):
    job = make_job("Software Engineer", description="2-5 years of experience.")
    assert evaluate(job, cfg).eligible  # minimum 2 <= max_years_experience 2


def test_unrelated_title_rejected(cfg):
    assert not evaluate(make_job("Product Designer"), cfg).eligible
    assert not evaluate(make_job("Account Executive"), cfg).eligible
