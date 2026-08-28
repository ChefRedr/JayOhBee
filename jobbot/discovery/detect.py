"""Pure ATS-detection logic: given a URL or page HTML, identify the provider
and extract its tenant/board identifier. No network access here (testable)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from jobbot.models.company import Provider


@dataclass
class ATSCandidate:
    provider: Provider
    identifier: str | None = None
    source_url: str = ""
    extra: dict = field(default_factory=dict)


# Path segments that are locales or boilerplate, not tenant identifiers.
_SKIP_SEGMENTS = {"en", "en-us", "en-gb", "embed", "jobs", "job", "careers", "search", "external"}

_WORKDAY_HOST_RE = re.compile(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com$", re.IGNORECASE)


def detect_from_url(url: str) -> ATSCandidate | None:
    """Detect an ATS provider + identifier from a single URL."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]

    def first_real_segment() -> str | None:
        for seg in segments:
            if seg.lower() not in _SKIP_SEGMENTS:
                return seg
        return None

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
                "job-boards.eu.greenhouse.io"):
        return ATSCandidate(Provider.GREENHOUSE, first_real_segment(), url)
    if host == "boards-api.greenhouse.io":
        # /v1/boards/{token}/...
        try:
            token = segments[segments.index("boards") + 1]
        except (ValueError, IndexError):
            token = None
        return ATSCandidate(Provider.GREENHOUSE, token, url)
    if host.endswith("greenhouse.io"):
        # embed URLs carry ?for=token
        match = re.search(r"[?&]for=([A-Za-z0-9_-]+)", url)
        return ATSCandidate(Provider.GREENHOUSE, match.group(1) if match else None, url)

    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        return ATSCandidate(Provider.LEVER, first_real_segment(), url)
    if host == "api.lever.co":
        # /v0/postings/{site}
        try:
            site = segments[segments.index("postings") + 1]
        except (ValueError, IndexError):
            site = None
        return ATSCandidate(Provider.LEVER, site, url)

    if host == "jobs.ashbyhq.com":
        return ATSCandidate(Provider.ASHBY, first_real_segment(), url)
    if host == "api.ashbyhq.com" and "job-board" in segments:
        try:
            name = segments[segments.index("job-board") + 1]
        except IndexError:
            name = None
        return ATSCandidate(Provider.ASHBY, name, url)

    wd = _WORKDAY_HOST_RE.match(host)
    if wd:
        tenant = wd.group(1).lower()
        site = first_real_segment()
        extra = {"workday_host": host}
        if site and site.lower() != "wday":
            extra["workday_site"] = site
        return ATSCandidate(Provider.WORKDAY, tenant, url, extra)

    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        return ATSCandidate(Provider.SMARTRECRUITERS, segments[0] if segments else None, url)
    if host == "api.smartrecruiters.com":
        try:
            ident = segments[segments.index("companies") + 1]
        except (ValueError, IndexError):
            ident = None
        return ATSCandidate(Provider.SMARTRECRUITERS, ident, url)

    if host.endswith(".icims.com"):
        return ATSCandidate(Provider.ICIMS, host.split(".")[0], url)

    if "oraclecloud.com" in host and ("hcmui" in url.lower() or "cxs" in url.lower() or "recruiting" in url.lower()):
        return ATSCandidate(Provider.ORACLE, host.split(".")[0], url)
    if "successfactors" in host or host.startswith("career") and "sap" in host:
        return ATSCandidate(Provider.SUCCESSFACTORS, None, url)

    return None


# Ranked so the strongest evidence wins when a page links several ATSes
_PROVIDER_PRIORITY = [
    Provider.GREENHOUSE,
    Provider.LEVER,
    Provider.ASHBY,
    Provider.SMARTRECRUITERS,
    Provider.WORKDAY,
    Provider.ICIMS,
    Provider.ORACLE,
    Provider.SUCCESSFACTORS,
]

_URL_RE = re.compile(r"""https?://[^\s"'<>\\)]+""")


def detect_from_html(html: str, base_url: str = "") -> list[ATSCandidate]:
    """Scan raw HTML (links, embedded API calls, scripts) for ATS clues.

    Returns candidates ordered by confidence: identifier-bearing matches first,
    then by provider priority.
    """
    candidates: dict[tuple, ATSCandidate] = {}
    for match in _URL_RE.finditer(html):
        cand = detect_from_url(match.group(0))
        if cand is None:
            continue
        key = (cand.provider, cand.identifier)
        if key not in candidates or (cand.extra and not candidates[key].extra):
            candidates[key] = cand

    def rank(c: ATSCandidate) -> tuple:
        prio = _PROVIDER_PRIORITY.index(c.provider) if c.provider in _PROVIDER_PRIORITY else 99
        return (0 if c.identifier else 1, prio)

    return sorted(candidates.values(), key=rank)
