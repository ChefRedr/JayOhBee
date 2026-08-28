from __future__ import annotations

import httpx

from jobbot.models.company import Company
from jobbot.models.job import Job

USER_AGENT = "jobbot/0.1 (personal job-search assistant)"

DEFAULT_TIMEOUT = httpx.Timeout(30.0)


class SourceError(Exception):
    """Raised when a source cannot fetch jobs. `retryable` guides retry policy."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class JobSource:
    """Fetches all current jobs for one company in as few requests as possible."""

    provider: str = "unknown"

    def fetch_jobs(self, company: Company) -> list[Job]:
        raise NotImplementedError

    # shared HTTP helper -------------------------------------------------
    def _get(self, url: str, **kwargs) -> httpx.Response:
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise SourceError(f"timeout fetching {url}: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"http error fetching {url}: {exc}", retryable=True) from exc
        if resp.status_code == 404:
            raise SourceError(f"404 from {url} (identifier may be wrong)", retryable=False)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise SourceError(f"{resp.status_code} from {url}", retryable=True)
        if resp.status_code >= 400:
            raise SourceError(f"{resp.status_code} from {url}", retryable=False)
        return resp
