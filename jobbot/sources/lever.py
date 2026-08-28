"""Lever public Postings API.

One request returns all published postings:
https://api.lever.co/v0/postings/{site}?mode=json
"""
from __future__ import annotations

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import JobSource, SourceError

API = "https://api.lever.co/v0/postings/{site}?mode=json"


class LeverSource(JobSource):
    provider = "lever"

    def fetch_jobs(self, company: Company) -> list[Job]:
        site = company.provider_identifier
        if not site:
            raise SourceError(f"{company.name}: no lever site configured")
        data = self._get(API.format(site=site)).json()
        if not isinstance(data, list):
            raise SourceError(f"{company.name}: unexpected lever response shape")
        jobs = []
        for item in data:
            categories = item.get("categories") or {}
            jobs.append(
                Job(
                    company=company.name,
                    external_id=str(item.get("id", "")),
                    title=item.get("text", ""),
                    location=categories.get("location"),
                    description=item.get("descriptionPlain") or item.get("description"),
                    job_url=item.get("hostedUrl", ""),
                    apply_url=item.get("applyUrl") or (item.get("hostedUrl", "") + "/apply"),
                    source_provider=self.provider,
                    posted_at=str(item.get("createdAt", "")) or None,
                    department=categories.get("team") or categories.get("department"),
                )
            )
        return jobs
