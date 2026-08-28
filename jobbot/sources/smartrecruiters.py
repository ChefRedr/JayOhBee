"""SmartRecruiters public postings API.

https://api.smartrecruiters.com/v1/companies/{company}/postings (paginated)
"""
from __future__ import annotations

from jobbot.models.company import Company
from jobbot.models.job import Job
from jobbot.sources.base import JobSource, SourceError

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
PAGE_LIMIT = 100


class SmartRecruitersSource(JobSource):
    provider = "smartrecruiters"

    def fetch_jobs(self, company: Company) -> list[Job]:
        ident = company.provider_identifier
        if not ident:
            raise SourceError(f"{company.name}: no smartrecruiters identifier configured")
        jobs: list[Job] = []
        offset = 0
        while True:
            data = self._get(
                API.format(company=ident),
                params={"limit": PAGE_LIMIT, "offset": offset},
            ).json()
            content = data.get("content", [])
            for item in content:
                posting_id = str(item.get("id", ""))
                location = item.get("location") or {}
                loc_str = ", ".join(
                    p for p in [location.get("city"), location.get("region"), location.get("country")] if p
                ) or None
                job_url = f"https://jobs.smartrecruiters.com/{ident}/{posting_id}"
                jobs.append(
                    Job(
                        company=company.name,
                        external_id=posting_id,
                        title=item.get("name", ""),
                        location=loc_str,
                        description=None,  # detail requires a per-job request; fetched lazily if needed
                        job_url=job_url,
                        apply_url=job_url,
                        source_provider=self.provider,
                        posted_at=item.get("releasedDate"),
                        department=(item.get("department") or {}).get("label"),
                    )
                )
            offset += len(content)
            if len(content) < PAGE_LIMIT or offset >= data.get("totalFound", 0):
                break
        return jobs
