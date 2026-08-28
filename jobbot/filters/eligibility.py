"""Deterministic new-grad / entry-level SWE filter. No ML, no scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jobbot.config import FilterConfig
from jobbot.models.job import Job

INTERNSHIP_RE = re.compile(r"\bintern(ship)?s?\b|\bco[- ]?op\b", re.IGNORECASE)

# "3+ years", "4 + years", "five (5) years", "3-5 years", "2 yrs"
YEARS_RE = re.compile(
    r"\(?(?:(\d{1,2})\)?\s*(?:-|–|to)\s*)?\(?(\d{1,2})\)?\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)


@dataclass
class FilterDecision:
    eligible: bool
    reason: str


def _contains_any(text: str, terms: list[str]) -> str | None:
    lowered = text.lower()
    for term in terms:
        if term.lower() in lowered:
            return term
    return None


def _contains_word(text: str, terms: list[str]) -> str | None:
    lowered = text.lower()
    for term in terms:
        if re.search(rf"\b{re.escape(term.lower())}\b", lowered):
            return term
    return None


def _required_years(description: str) -> int | None:
    """Best-effort minimum years of experience demanded by the description.

    Only counts mentions adjacent to experience requirements, e.g.
    '3+ years of experience', '2-4 years experience'. Returns the highest
    minimum found, or None.
    """
    worst: int | None = None
    for match in YEARS_RE.finditer(description):
        window = description[match.end(): match.end() + 60].lower()
        before = description[max(0, match.start() - 40): match.start()].lower()
        if "experience" not in window and "experience" not in before and "of industry" not in window:
            continue
        minimum = int(match.group(1) or match.group(2))
        if worst is None or minimum > worst:
            worst = minimum
    return worst


def evaluate(job: Job, cfg: FilterConfig) -> FilterDecision:
    title = job.title or ""
    description = job.description or ""
    combined = f"{title}\n{description}"

    if term := _contains_any(title, cfg.negative_title_terms):
        return FilterDecision(False, f"negative title term: {term!r}")

    if cfg.reject_internships and INTERNSHIP_RE.search(title):
        return FilterDecision(False, "internship/co-op")

    positive = _contains_any(title, cfg.positive_title_terms)
    adjacent = _contains_any(title, cfg.adjacent_title_terms)
    if not positive and not adjacent:
        return FilterDecision(False, "title does not match any target role")
    # "new grad" alone also matches sales/ops postings — the title must
    # additionally look like an engineering role
    if not re.search(r"software|engineer|developer|\bswe\b|\bsde\b|programmer", title, re.IGNORECASE):
        return FilterDecision(False, "matched entry-level marker but not an engineering title")
    if not positive and adjacent:
        marker = _contains_any(combined, cfg.entry_level_markers)
        if not marker:
            return FilterDecision(False, f"adjacent role {adjacent!r} without entry-level marker")

    years = _required_years(description)
    if years is not None and years > cfg.max_years_experience:
        return FilterDecision(False, f"requires {years}+ years experience")

    # locations match on whole words ("NY" must not match "Sunnyvale");
    # a job with NO location deliberately passes the allow-list (remote/unknown)
    location = job.location or ""
    if cfg.location_deny and _contains_word(location, cfg.location_deny):
        return FilterDecision(False, f"location denied: {location!r}")
    if cfg.location_allow and location and not _contains_word(location, cfg.location_allow):
        return FilterDecision(False, f"location not in allow list: {location!r}")

    return FilterDecision(True, "matches entry-level SWE rules")
