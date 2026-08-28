"""Greenhouse public job board API.

One request returns every open job for a board token:
https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
"""
from __future__ import annotations

import html
import re

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import JobSource, SourceError

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return TAG_RE.sub(" ", html.unescape(text or ""))


class GreenhouseSource(JobSource):
    provider = "greenhouse"

    def fetch_jobs(self, company: Company) -> list[Job]:
        token = company.provider_identifier
        if not token:
            raise SourceError(f"{company.name}: no greenhouse board token configured")
        data = self._get(API.format(token=token)).json()
        jobs = []
        for item in data.get("jobs", []):
            job_url = item.get("absolute_url") or ""
            jobs.append(
                Job(
                    company=company.name,
                    external_id=str(item.get("id", "")),
                    title=item.get("title", ""),
                    location=(item.get("location") or {}).get("name"),
                    description=strip_html(item.get("content", "")),
                    job_url=job_url,
                    apply_url=job_url,  # greenhouse hosted pages embed the form
                    source_provider=self.provider,
                    posted_at=item.get("first_published") or item.get("updated_at"),
                    department=", ".join(
                        d.get("name", "") for d in item.get("departments", []) if d
                    ) or None,
                )
            )
        return jobs
