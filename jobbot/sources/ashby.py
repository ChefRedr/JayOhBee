"""Ashby public job-board posting API.

https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true
"""
from __future__ import annotations

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import JobSource, SourceError

API = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"


class AshbySource(JobSource):
    provider = "ashby"

    def fetch_jobs(self, company: Company) -> list[Job]:
        name = company.provider_identifier
        if not name:
            raise SourceError(f"{company.name}: no ashby job board name configured")
        data = self._get(API.format(name=name)).json()
        jobs = []
        for item in data.get("jobs", []):
            if item.get("isListed") is False:
                continue
            comp = (item.get("compensation") or {}).get("compensationTierSummary")
            jobs.append(
                Job(
                    company=company.name,
                    external_id=str(item.get("id", "")),
                    title=item.get("title", ""),
                    location=item.get("location"),
                    description=item.get("descriptionPlain") or item.get("descriptionHtml"),
                    job_url=item.get("jobUrl", ""),
                    apply_url=item.get("applyUrl") or item.get("jobUrl", ""),
                    source_provider=self.provider,
                    posted_at=item.get("publishedAt"),
                    salary=comp,
                    department=item.get("department") or item.get("team"),
                )
            )
        return jobs
