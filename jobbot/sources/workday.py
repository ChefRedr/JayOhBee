"""Workday CXS jobs endpoint (the JSON API behind myworkdayjobs.com sites).

POST https://{host}/wday/cxs/{tenant}/{site}/jobs
with {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

Company config requirements (in extra fields):
  provider_identifier: tenant (e.g. "nvidia")
  workday_host: full host (e.g. "nvidia.wd5.myworkdayjobs.com")
  workday_site: site name (e.g. "NVIDIAExternalCareerSite")
"""
from __future__ import annotations

import httpx

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import DEFAULT_TIMEOUT, USER_AGENT, JobSource, SourceError

PAGE_SIZE = 20
MAX_JOBS = 2000  # safety cap


class WorkdaySource(JobSource):
    provider = "workday"

    def fetch_jobs(self, company: Company) -> list[Job]:
        tenant = company.provider_identifier
        host = company.extra.get("workday_host")
        site = company.extra.get("workday_site")
        if not (tenant and host and site):
            raise SourceError(
                f"{company.name}: workday needs provider_identifier (tenant), "
                "workday_host and workday_site"
            )
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        jobs: list[Job] = []
        offset = 0
        total = None
        while total is None or (offset < total and offset < MAX_JOBS):
            payload = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""}
            try:
                resp = httpx.post(
                    endpoint,
                    json=payload,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=DEFAULT_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"workday request failed for {company.name}: {exc}", retryable=True) from exc
            if resp.status_code >= 500 or resp.status_code == 429:
                raise SourceError(f"{resp.status_code} from {endpoint}", retryable=True)
            if resp.status_code >= 400:
                raise SourceError(f"{resp.status_code} from {endpoint}")
            data = resp.json()
            total = data.get("total", 0)
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for item in postings:
                external_path = item.get("externalPath", "")
                job_url = f"https://{host}/en-US/{site}{external_path}"
                bullets = item.get("bulletFields") or []
                req_id = bullets[0] if bullets else external_path
                jobs.append(
                    Job(
                        company=company.name,
                        external_id=str(req_id),
                        title=item.get("title", ""),
                        location=item.get("locationsText"),
                        description=None,  # detail requires a per-job request
                        job_url=job_url,
                        apply_url=job_url,
                        source_provider=self.provider,
                        posted_at=item.get("postedOn"),
                    )
                )
            offset += PAGE_SIZE
        return jobs
