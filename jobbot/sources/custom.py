"""Fallback source for companies with custom careers sites.

Tries structured HTML parsing of the configured jobs_url; per-company logic is
intentionally out of scope for the MVP. Companies that need real browser
scraping should be marked requires_browser and will surface in `jobbot status`
as unsupported until an adapter exists.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import JobSource, SourceError


class CustomSource(JobSource):
    provider = "custom"

    def fetch_jobs(self, company: Company) -> list[Job]:
        url = company.jobs_url or company.careers_url
        if not url:
            raise SourceError(f"{company.name}: no jobs_url configured for custom source")
        resp = self._get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs: list[Job] = []
        # Extremely conservative heuristic: anchor tags that look like job links.
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True)
            if not text or len(text) > 120:
                continue
            if not any(k in href.lower() for k in ("job", "position", "opening", "role")):
                continue
            absolute = httpx_urljoin(url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            jobs.append(
                Job(
                    company=company.name,
                    external_id="",
                    title=text,
                    job_url=absolute,
                    apply_url=absolute,
                    source_provider=self.provider,
                )
            )
        if not jobs:
            raise SourceError(
                f"{company.name}: custom source found no job links at {url} "
                "(page may require a browser)", retryable=False,
            )
        return jobs


def httpx_urljoin(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)
