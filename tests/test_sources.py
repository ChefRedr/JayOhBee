from jobbot.models.company import Company, Provider
from jobbot.sources.ashby import AshbySource
from jobbot.sources.greenhouse import GreenhouseSource
from jobbot.sources.lever import LeverSource


def company(provider, ident="examplecorp"):
    return Company(name="Example Corp", slug="example-corp",
                   provider=provider, provider_identifier=ident)


def test_greenhouse_normalization(fake_get, fixture_json):
    fake_get(fixture_json("greenhouse_jobs.json"))
    jobs = GreenhouseSource().fetch_jobs(company(Provider.GREENHOUSE))
    assert len(jobs) == 2
    job = jobs[0]
    assert job.company == "Example Corp"
    assert job.external_id == "4011001"
    assert job.title == "Software Engineer, New Grad"
    assert job.location == "San Francisco, CA"
    assert job.job_url.endswith("/jobs/4011001")
    assert job.apply_url == job.job_url
    assert job.source_provider == "greenhouse"
    assert "0-1 years" in job.description  # html stripped
    assert "<p>" not in job.description
    assert job.department == "Engineering"


def test_lever_normalization(fake_get, fixture_json):
    fake_get(fixture_json("lever_postings.json"))
    jobs = LeverSource().fetch_jobs(company(Provider.LEVER))
    assert len(jobs) == 2
    job = jobs[0]
    assert job.external_id == "aaaa-bbbb-cccc"
    assert job.title == "Software Engineer I - Backend"
    assert job.apply_url.endswith("/apply")
    assert job.location == "New York, NY"
    assert job.department == "Platform"


def test_ashby_normalization_skips_unlisted(fake_get, fixture_json):
    fake_get(fixture_json("ashby_jobs.json"))
    jobs = AshbySource().fetch_jobs(company(Provider.ASHBY))
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Software Engineer - New Grad (2026)"
    assert job.salary == "$120K - $150K"
    assert job.apply_url.endswith("/application")


def test_job_identity_stable_and_unique(fake_get, fixture_json):
    fake_get(fixture_json("greenhouse_jobs.json"))
    jobs = GreenhouseSource().fetch_jobs(company(Provider.GREENHOUSE))
    assert jobs[0].identity == "greenhouse:Example Corp:4011001"
    assert jobs[0].identity != jobs[1].identity


def test_job_identity_hash_fallback():
    from jobbot.models.job import Job

    a = Job(company="X", external_id="", title="SWE", job_url="https://x/1",
            apply_url="https://x/1", source_provider="custom")
    b = Job(company="X", external_id="", title="SWE", job_url="https://x/2",
            apply_url="https://x/2", source_provider="custom")
    assert a.identity != b.identity
    assert a.identity == a.identity
