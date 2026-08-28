"""Company source discovery (Stage A).

For each company without a verified configuration, work out where it publishes
jobs: find the careers page, detect the ATS, extract the tenant identifier, and
prove the source works by actually fetching jobs from it.

Discovery never guesses silently: anything uncertain is marked needs_review.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from jobbot.config import REPO_ROOT, load_companies, save_companies
from jobbot.discovery.detect import ATSCandidate, detect_from_html, detect_from_url
from jobbot.models.company import Company, DiscoveryStatus, Provider
from jobbot.sources import get_source
from jobbot.sources.base import DEFAULT_TIMEOUT, USER_AGENT, SourceError

log = logging.getLogger("jobbot.discovery")

# Providers we can probe directly by slug when no careers URL is known.
_PROBE_PROVIDERS = (Provider.GREENHOUSE, Provider.LEVER, Provider.ASHBY, Provider.SMARTRECRUITERS)

_CAREERS_LINK_HINTS = ("career", "job", "join", "opening", "position", "work-with-us", "hiring")


def _fetch(url: str) -> httpx.Response | None:
    try:
        return httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        log.debug("fetch failed for %s: %s", url, exc)
        return None


def _verify_candidate(company: Company, cand: ATSCandidate) -> int | None:
    """Try to fetch jobs using the candidate config. Returns the job count on
    success, None on failure."""
    trial = Company(
        name=company.name,
        slug=company.slug,
        provider=cand.provider,
        provider_identifier=cand.identifier,
        extra={**company.extra, **cand.extra},
    )
    source = get_source(cand.provider)
    if source is None:
        return None
    try:
        return len(source.fetch_jobs(trial))
    except SourceError as exc:
        log.debug("%s: candidate %s/%s failed verification: %s",
                  company.name, cand.provider, cand.identifier, exc)
        return None


def _greenhouse_board_name(token: str) -> str | None:
    resp = _fetch(f"https://boards-api.greenhouse.io/v1/boards/{token}")
    if resp is not None and resp.status_code == 200:
        try:
            return resp.json().get("name")
        except ValueError:
            return None
    return None


def _smartrecruiters_company_name(ident: str) -> str | None:
    resp = _fetch(f"https://api.smartrecruiters.com/v1/companies/{ident}")
    if resp is not None and resp.status_code == 200:
        try:
            return resp.json().get("name")
        except ValueError:
            return None
    return None


def _page_title(url: str) -> str | None:
    resp = _fetch(url)
    if resp is None or resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    parts = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string)
    og = soup.find("meta", property="og:site_name") or soup.find("meta", property="og:title")
    if og and og.get("content"):
        parts.append(og["content"])
    return " | ".join(parts) or None


def _names_match(company_name: str, board_name: str | None) -> bool:
    if not board_name:
        return False
    a = "".join(ch for ch in company_name.lower() if ch.isalnum())
    b = "".join(ch for ch in board_name.lower() if ch.isalnum())
    if not (a and b):
        return False
    if a in b or b in a:
        return True
    # fall back to the company's distinctive first word ("Scale AI" -> "scale")
    first = "".join(ch for ch in company_name.lower().split()[0] if ch.isalnum())
    return len(first) >= 4 and first in b


def _probe_board_name(provider: Provider, ident: str) -> str | None:
    """Independent evidence of who owns a probed board, per provider."""
    if provider == Provider.GREENHOUSE:
        return _greenhouse_board_name(ident)
    if provider == Provider.SMARTRECRUITERS:
        return _smartrecruiters_company_name(ident)
    if provider == Provider.LEVER:
        return _page_title(f"https://jobs.lever.co/{ident}")
    if provider == Provider.ASHBY:
        return _page_title(f"https://jobs.ashbyhq.com/{ident}")
    return None


def _slug_variants(company: Company) -> list[str]:
    slug = company.slug
    variants = [slug, slug.replace("-", ""), slug.replace("-", "_")]
    seen = set()
    return [v for v in variants if v and not (v in seen or seen.add(v))]


def _probe_by_slug(company: Company) -> tuple[ATSCandidate, int] | None:
    """Try known ATS endpoints using slug variants. A hit proves the endpoint
    serves jobs, but not necessarily *this* company's jobs, so callers should
    treat probe-only results as needs_review unless the name matches."""
    for provider in _PROBE_PROVIDERS:
        for ident in _slug_variants(company):
            cand = ATSCandidate(provider, ident, source_url=f"probe:{provider}")
            count = _verify_candidate(company, cand)
            if count is not None and count > 0:
                return cand, count
            time.sleep(0.2)
    return None


def _find_careers_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(" ", strip=True) or "").lower()
        blob = f"{href.lower()} {text}"
        if any(h in blob for h in _CAREERS_LINK_HINTS):
            links.append(urljoin(base_url, href))
    # de-dupe, keep order
    seen: set[str] = set()
    return [l for l in links if not (l in seen or seen.add(l))][:8]


def discover_company(company: Company) -> Company:
    """Populate provider/identifier/discovery_status for one company."""
    candidates: list[ATSCandidate] = []
    pages_scanned: list[str] = []

    urls_to_scan = [u for u in (company.jobs_url, company.careers_url) if u]
    followed = 0
    while urls_to_scan and followed < 6:
        url = urls_to_scan.pop(0)
        if url in pages_scanned:
            continue
        pages_scanned.append(url)
        followed += 1

        direct = detect_from_url(url)
        if direct and direct.identifier:
            candidates.append(direct)

        resp = _fetch(url)
        if resp is None:
            continue
        final = detect_from_url(str(resp.url))
        if final and final.identifier:
            candidates.append(final)
        candidates.extend(detect_from_html(resp.text, str(resp.url)))

        # If nothing conclusive yet, follow careers-ish links one level deep.
        if not any(c.identifier for c in candidates) and followed < 6:
            same_host = urlparse(url).hostname
            for link in _find_careers_links(resp.text, str(resp.url)):
                if urlparse(link).hostname == same_host or detect_from_url(link):
                    urls_to_scan.append(link)
        time.sleep(0.3)

    # Verify candidates in confidence order.
    for cand in candidates:
        if not cand.identifier:
            continue
        count = _verify_candidate(company, cand)
        if count is None:
            continue
        company.provider = cand.provider
        company.provider_identifier = cand.identifier
        company.extra.update(cand.extra)
        company.jobs_url = cand.source_url if cand.source_url.startswith("http") else company.jobs_url
        company.discovery_status = DiscoveryStatus.VERIFIED
        company.last_verified = date.today().isoformat()
        company.notes = f"verified via careers page; {count} jobs at discovery"
        return company

    # No careers-page evidence — probe common ATS endpoints by slug.
    probe = _probe_by_slug(company)
    if probe:
        cand, count = probe
        company.provider = cand.provider
        company.provider_identifier = cand.identifier
        company.extra.update(cand.extra)
        board_name = _probe_board_name(cand.provider, cand.identifier)
        if _names_match(company.name, board_name):
            company.discovery_status = DiscoveryStatus.VERIFIED
            company.last_verified = date.today().isoformat()
            company.notes = f"slug probe; board name matches ({board_name!r}); {count} jobs"
        else:
            company.discovery_status = DiscoveryStatus.NEEDS_REVIEW
            company.notes = (
                f"slug probe hit {cand.provider}:{cand.identifier} with {count} jobs — "
                "confirm the board actually belongs to this company"
            )
        return company

    if candidates:
        best = candidates[0]
        company.provider = best.provider
        company.discovery_status = DiscoveryStatus.NEEDS_REVIEW
        company.notes = f"detected {best.provider} but could not verify an identifier"
    elif pages_scanned:
        company.discovery_status = DiscoveryStatus.NEEDS_REVIEW
        company.notes = "careers page reachable but no supported ATS detected (may need a browser)"
        company.requires_browser = True
    else:
        company.discovery_status = DiscoveryStatus.FAILED
        company.notes = "no careers_url configured and slug probes found nothing"
    return company


def run_discovery(limit: int | None = None, rediscover: bool = False) -> dict[str, int]:
    """Discover sources for companies without verified configs. Saves the
    registry incrementally so an interrupted run loses nothing."""
    companies = load_companies()
    todo = [
        c for c in companies
        if c.enabled and (rediscover or c.discovery_status != DiscoveryStatus.VERIFIED)
    ]
    todo.sort(key=lambda c: c.extra.get("rank") or 10_000)

    # curated careers-URL hints for companies with nothing configured
    hints_path = REPO_ROOT / "data" / "careers_urls.yaml"
    if hints_path.exists():
        import yaml

        hints = yaml.safe_load(hints_path.read_text()) or {}
        for c in todo:
            if not c.careers_url and c.slug in hints:
                c.careers_url = hints[c.slug]
    if limit:
        todo = todo[:limit]
    log.info("discovering sources for %d companies", len(todo))

    for i, company in enumerate(todo, 1):
        try:
            discover_company(company)
        except Exception as exc:  # noqa: BLE001 — one company must not stop the run
            log.error("%s: discovery crashed: %s", company.name, exc)
            company.discovery_status = DiscoveryStatus.FAILED
            company.notes = f"discovery error: {type(exc).__name__}: {exc}"
        log.info("[%d/%d] %s -> %s (%s)", i, len(todo), company.name,
                 company.provider, company.discovery_status)
        if i % 10 == 0 or i == len(todo):
            save_companies(companies)
        time.sleep(0.5)

    save_companies(companies)
    return summarize(companies)


def summarize(companies: list[Company] | None = None) -> dict[str, int]:
    companies = companies if companies is not None else load_companies()
    summary: dict[str, int] = {"total": len(companies)}
    for c in companies:
        if c.discovery_status == DiscoveryStatus.VERIFIED:
            summary[str(c.provider)] = summary.get(str(c.provider), 0) + 1
        else:
            summary[str(c.discovery_status)] = summary.get(str(c.discovery_status), 0) + 1
    return summary
