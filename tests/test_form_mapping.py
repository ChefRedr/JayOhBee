import pytest

from jobbot.applications.form_mapping import pick_option, resolve
from jobbot.config import ApplicantProfile


@pytest.fixture
def profile():
    return ApplicantProfile(
        first_name="Test", last_name="Applicant", email="t@example.com",
        phone="555-0100", linkedin_url="https://linkedin.com/in/test",
        github_url="https://github.com/test", school="State University",
        degree="BS", major="Computer Science",
        graduation_month="May", graduation_year="2026",
        answers={
            "authorized_to_work_us": "yes",
            "require_sponsorship": "no",
            "willing_to_relocate": "yes",
        },
    )


def test_identity_fields_resolve(profile):
    assert resolve("First Name *", profile).value == "Test"
    assert resolve("Email", profile).value == "t@example.com"
    assert resolve("LinkedIn Profile", profile).value == "https://linkedin.com/in/test"
    assert resolve("School", profile).value == "State University"


def test_configured_answers_resolve(profile):
    assert resolve("Are you legally authorized to work in the United States?", profile).value == "yes"
    assert resolve("Will you now or in the future require sponsorship?", profile).value == "no"


def test_unknown_question_returns_none(profile):
    assert resolve("Describe your favorite distributed systems paper", profile) is None
    assert resolve("What is your desired start date?", profile) is None


def test_known_topic_without_configured_answer_returns_none(profile):
    # gpa matches a known topic but is not configured -> must go to review
    assert resolve("What is your GPA?", profile) is None
    # EEO questions unconfigured -> review
    assert resolve("Gender", profile) is None
    assert resolve("Veteran Status", profile) is None


def test_essay_questions_never_auto_answered(profile):
    profile.answers["why_us"] = "should never be used by matcher"
    assert resolve("Why do you want to work here?", profile) is None
    assert resolve("Cover Letter", profile) is None
    assert resolve("Do you hold an active security clearance?", profile) is None


def test_pick_option_exact_and_yes_no():
    assert pick_option("yes", ["Select...", "Yes", "No"]) == "Yes"
    assert pick_option("no", ["Select...", "Yes", "No"]) == "No"
    assert pick_option("United States", ["Canada", "United States", "Other"]) == "United States"


def test_pick_option_ambiguous_returns_none():
    assert pick_option("yes", ["Yes, with conditions", "Yes, immediately", "No"]) is None
    assert pick_option("blue", ["Red", "Green"]) is None
