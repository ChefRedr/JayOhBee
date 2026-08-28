"""Deterministic mapping from application-form question labels to configured
applicant answers. If a label maps to nothing, the caller must send the
application to manual review — this module never invents an answer."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jobbot.config import ApplicantProfile


@dataclass
class Resolved:
    value: str
    matched_topic: str


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", label.lower())).strip()


def _matches(pattern: str, norm_label: str) -> bool:
    """Whole-word containment: 'city' must not match 'capacity',
    'major' must not match 'majority'."""
    return re.search(rf"\b{re.escape(pattern)}\b", norm_label) is not None


# Ordered (topic, patterns, profile getter). First match wins; patterns are
# substrings checked against the normalized label.
def _rules(p: ApplicantProfile) -> list[tuple[str, list[str], str]]:
    a = p.answers
    return [
        ("first_name", ["first name"], p.first_name),
        ("last_name", ["last name", "surname", "family name"], p.last_name),
        ("full_name", ["full name", "your name", "legal name"], p.full_name),
        ("preferred_name", ["preferred name"], p.preferred_name or p.first_name),
        ("email", ["email"], p.email),
        ("phone", ["phone", "mobile number"], p.phone),
        ("linkedin", ["linkedin"], p.linkedin_url),
        ("github", ["github"], p.github_url),
        ("portfolio", ["portfolio", "personal website", "website url", "personal site"], p.portfolio_url),
        ("school", ["school", "university", "college name", "institution"], p.school),
        ("degree", ["degree"], p.degree),
        ("major", ["major", "discipline", "field of study"], p.major),
        ("graduation", ["graduation date", "grad date", "graduation year", "expected graduation"],
         f"{p.graduation_month} {p.graduation_year}".strip()),
        ("location", ["current location", "city", "where are you located", "where do you live",
                      "currently located", "where do you currently live", "currently based",
                      "state province or region"],
         ", ".join(x for x in (p.city, p.state) if x)),
        # employment status: a student profile (future graduation) has factual
        # derived answers; override via answers.current_company / answers.job_title
        ("current_company", ["current company", "current employer", "most recent employer",
                             "current or most recent company"],
         a.get("current_company", f"{p.school} (student)" if p.school and p.graduation_year else "")),
        ("start_date", ["when can you start", "earliest start date", "available to start",
                        "date available", "when are you available"],
         a.get("start_date",
               f"Upon graduation, {p.graduation_month} {p.graduation_year}".strip(", ")
               if p.graduation_year else "")),
        ("address", ["street address", "address line"], p.address),
        ("zip", ["zip", "postal code"], p.zip),
        ("country", ["country"], p.country),
        # Yes/no policy questions — ONLY from explicit configured answers.
        ("authorized_to_work_us", ["authorized to work", "legally authorized", "eligible to work",
                                   "right to work", "work authorization"],
         a.get("authorized_to_work_us", "")),
        ("require_sponsorship", ["sponsorship", "sponsor"], a.get("require_sponsorship", "")),
        ("previously_employed_here", ["previously employed", "ever worked for", "former employee",
                                      "currently or previously"], a.get("previously_employed_here", "")),
        ("willing_to_relocate", ["relocat"], a.get("willing_to_relocate", p.willing_to_relocate)),
        ("over_18", ["18 years", "over 18", "at least 18"], a.get("over_18", "")),
        # factual: an applicant with a future graduation date is a student/new grad
        ("student_or_new_grad", ["student or new grad", "student or recent grad"],
         a.get("student_or_new_grad", "yes" if p.graduation_year else "")),
        ("gpa", ["gpa", "grade point"], a.get("gpa", "")),
        ("salary", ["salary", "compensation expectation", "expected pay"],
         a.get("salary", p.minimum_salary)),
        ("how_did_you_hear", ["how did you hear", "how you heard"], a.get("how_did_you_hear", "")),
        # Demographic/EEO — answered only when explicitly configured.
        ("gender", ["gender"], a.get("gender", "")),
        ("race", ["race", "ethnicity", "hispanic or latino"], a.get("race", "")),
        ("veteran_status", ["veteran"], a.get("veteran_status", "")),
        ("disability_status", ["disability"], a.get("disability_status", "")),
    ]


# Labels that must never be auto-answered even if a rule matched loosely.
_ALWAYS_REVIEW = [
    "why do you want", "why are you interested", "cover letter", "essay",
    "tell us about", "describe a time", "security clearance", "conflict of interest",
    "non compete", "criminal", "background check authorization",
]


def resolve(label: str, profile: ApplicantProfile) -> Resolved | None:
    """Return the configured answer for a form label, or None if unknown."""
    norm = _norm(label)
    if not norm:
        return None
    for phrase in _ALWAYS_REVIEW:
        if phrase in norm:
            return None
    if "high school" in norm:  # never answer high-school questions with the university
        return None
    # a bare "Name" field (Ashby style) means the full name; only exact match,
    # so "company name" etc. never receives the applicant's name
    if norm in ("name", "your name") and profile.full_name:
        return Resolved(value=profile.full_name, matched_topic="full_name")
    for topic, patterns, value in _rules(profile):
        if any(_matches(pat, norm) for pat in patterns):
            if value:
                return Resolved(value=str(value), matched_topic=topic)
            return None  # matched a known topic but no answer configured -> review
    return None


def pick_option(answer: str, options: list[str]) -> str | None:
    """Choose a <select>/radio option matching a configured answer.

    Deterministic: exact case-insensitive match first, then a yes/no mapping,
    then unique substring containment. Returns None when ambiguous."""
    answer_n = _norm(answer)
    options_n = {_norm(o): o for o in options if o and _norm(o) not in ("select", "please select", "")}

    if answer_n in options_n:
        return options_n[answer_n]

    if answer_n in ("yes", "no", "true", "false", "y", "n"):
        want = "yes" if answer_n in ("yes", "true", "y") else "no"
        # whole-word only: "no" must not match "Not sure" or "Not applicable"
        pool = [o for n, o in options_n.items() if re.match(rf"{want}\b", n)]
        if len(pool) == 1:
            return pool[0]

    containing = [
        o for n, o in options_n.items()
        if answer_n and re.search(rf"\b{re.escape(answer_n)}\b", n)
    ]
    if len(containing) == 1:
        return containing[0]
    return None
