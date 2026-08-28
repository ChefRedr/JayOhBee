"""Configuration loading: settings, company registry, filters, applicant profile."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from jobbot.models.company import Company

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("JOBBOT_CONFIG_DIR", REPO_ROOT / "config"))
STATE_DIR = Path(os.environ.get("JOBBOT_STATE_DIR", REPO_ROOT / "state"))

COMPANIES_PATH = CONFIG_DIR / "companies.yaml"
FILTERS_PATH = CONFIG_DIR / "filters.yaml"
APPLICANT_PATH = Path(os.environ.get("JOBBOT_APPLICANT", CONFIG_DIR / "applicant.yaml"))
DB_PATH = Path(os.environ.get("JOBBOT_DB", STATE_DIR / "jobbot.db"))


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def auto_apply_enabled() -> bool:
    """Global kill switch. Applications are only ever submitted when this is on."""
    return env_flag("AUTO_APPLY", default=False)


# ---------------------------------------------------------------- companies

def load_companies(path: Path | None = None) -> list[Company]:
    path = path or COMPANIES_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or []
    return [Company.from_dict(entry) for entry in data]


def save_companies(companies: list[Company], path: Path | None = None) -> None:
    path = path or COMPANIES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [c.to_dict() for c in sorted(companies, key=lambda c: c.slug)]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


# ---------------------------------------------------------------- filters

@dataclass
class FilterConfig:
    positive_title_terms: list[str] = field(default_factory=list)
    adjacent_title_terms: list[str] = field(default_factory=list)
    entry_level_markers: list[str] = field(default_factory=list)
    negative_title_terms: list[str] = field(default_factory=list)
    reject_internships: bool = True
    max_years_experience: int = 2
    location_allow: list[str] = field(default_factory=list)  # empty = allow all
    location_deny: list[str] = field(default_factory=list)
    # title keywords that align with the applicant's background; used only to
    # ORDER applications (best-fit first), never to include/exclude jobs
    rank_boost_terms: list[str] = field(default_factory=list)


def load_filters(path: Path | None = None) -> FilterConfig:
    path = path or FILTERS_PATH
    if not path.exists():
        return FilterConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return FilterConfig(**{k: v for k, v in data.items() if k in FilterConfig.__dataclass_fields__})


# ---------------------------------------------------------------- applicant

@dataclass
class ApplicantProfile:
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    school: str = ""
    degree: str = ""
    major: str = ""
    graduation_month: str = ""
    graduation_year: str = ""
    work_authorization: str = ""
    requires_sponsorship_now: str = ""
    requires_sponsorship_future: str = ""
    minimum_salary: str = ""
    willing_to_relocate: str = ""
    preferred_locations: list[str] = field(default_factory=list)
    resume_path: str = ""
    # Explicit predefined answers for application questions, keyed by a
    # normalized question topic. The bot only answers questions covered here
    # or by the identity fields above — it never infers factual answers.
    answers: dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def validate(self) -> list[str]:
        problems = []
        for req in ("first_name", "last_name", "email", "phone", "resume_path"):
            if not getattr(self, req):
                problems.append(f"missing required applicant field: {req}")
        if self.resume_path and not Path(self.resume_path).expanduser().exists():
            problems.append(f"resume file not found: {self.resume_path}")
        return problems


def load_applicant(path: Path | None = None) -> ApplicantProfile:
    path = path or APPLICANT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Applicant profile not found at {path}. "
            "Copy config/applicant.example.yaml to config/applicant.yaml and fill it in "
            "(it is gitignored), or set JOBBOT_APPLICANT."
        )
    data = yaml.safe_load(path.read_text()) or {}
    known = {k: v for k, v in data.items() if k in ApplicantProfile.__dataclass_fields__ and v is not None}
    # normalize answer values to strings
    answers = known.get("answers") or {}
    known["answers"] = {str(k): str(v) for k, v in answers.items() if v is not None}
    return ApplicantProfile(**known)
