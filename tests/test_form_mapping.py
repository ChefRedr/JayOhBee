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


def test_word_boundary_matching_prevents_guessing(profile):
    # H3 regression: substring matches must not fire inside longer words
    assert resolve("What is your production capacity?", profile) is None
    assert resolve("Do you agree with the majority opinion?", profile) is None
    assert resolve("Did you attend high school in the US?", profile) is None
    # while real questions still resolve
    profile.city, profile.state = "Austin", "TX"
    assert resolve("City", profile).value == "Austin, TX"
    assert resolve("Major", profile).value == "Computer Science"


def test_pick_option_no_never_matches_not_sure():
    # M1 regression
    assert pick_option("no", ["Yes", "Not sure"]) is None
    assert pick_option("no", ["Yes", "Not applicable"]) is None
    assert pick_option("no", ["Yes", "No, I do not"]) == "No, I do not"


def test_student_derived_answers(profile):
    profile.city, profile.state = "Evanston", "IL"
    assert resolve("Where are you currently located?", profile).value == "Evanston, IL"
    assert resolve("Which state, province, or region do you currently live in?", profile).value == "Evanston, IL"
    assert "State University (student)" == resolve("Current Company", profile).value
    assert "2026" in resolve("When can you start a new role?", profile).value
    assert resolve("Do you currently have unrestricted work authorization?", profile).value == "yes"
    # override still wins
    profile.answers["current_company"] = "Acme Corp"
    assert resolve("Current employer", profile).value == "Acme Corp"


def test_auto_acknowledge_gated(profile):
    label = "Please read the arbitration agreement below and acknowledge"
    assert resolve(label, profile) is None  # opt-in not set -> review
    profile.answers["auto_acknowledge"] = "yes"
    r = resolve(label, profile)
    assert r is not None and r.value == "__ACK__"
    assert resolve("I hereby certify that my answers are true", profile).value == "__ACK__"
    # factual questions about agreements are NOT acknowledgments
    r = resolve("Are you currently subject to any agreement with a former employer?", profile)
    assert r is None  # restrictive_agreements unconfigured -> review
    profile.answers["restrictive_agreements"] = "no"
    assert resolve("Are you currently subject to any agreement with a former employer?", profile).value == "no"
    # hard stops survive the opt-in
    assert resolve("Do you have an active security clearance?", profile) is None
    assert resolve("Why do you want to work here? I agree this is required.", profile) is None


def test_language_checkboxes(profile):
    assert resolve("English (ENG)", profile).value == "yes"
    assert resolve("Spanish (SPA)", profile).value == "no"
    assert resolve("Cantonese (CANT)", profile).value == "no"


def test_new_topics(profile):
    profile.answers.update({
        "open_to_office": "yes", "interview_language": "Python",
        "active_immigration_case": "no", "essential_functions": "yes",
    })
    assert resolve("Are you able to work from our US office three days per week?", profile).value == "yes"
    assert resolve("What is your preferred programming language for interviews?", profile).value == "Python"
    assert resolve("Do you currently have an active immigration case (ex H-1B)?", profile).value == "no"
    assert resolve("Can you perform the essential functions of this role?", profile).value == "yes"
    assert resolve("End date year", profile).value == "2026"


def test_pick_affirmative():
    from jobbot.applications.form_mapping import pick_affirmative
    assert pick_affirmative(["I Agree", "I Do Not Agree"]) == "I Agree"
    assert pick_affirmative(["Acknowledge/Confirm"]) == "Acknowledge/Confirm"
    assert pick_affirmative(["Yes", "Agree"]) is None  # ambiguous
    assert pick_affirmative(["Decline", "Disagree"]) is None
