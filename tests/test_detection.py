from jobbot.discovery.detect import detect_from_html, detect_from_url
from jobbot.models.company import Provider


def test_greenhouse_board_url():
    c = detect_from_url("https://boards.greenhouse.io/stripe/jobs/123")
    assert c.provider == Provider.GREENHOUSE
    assert c.identifier == "stripe"


def test_greenhouse_job_boards_url():
    c = detect_from_url("https://job-boards.greenhouse.io/duolingo")
    assert c.provider == Provider.GREENHOUSE
    assert c.identifier == "duolingo"


def test_greenhouse_embed_url():
    c = detect_from_url("https://boards.greenhouse.io/embed/job_board?for=examplecorp")
    assert c.provider == Provider.GREENHOUSE
    assert c.identifier == "examplecorp"


def test_lever_url():
    c = detect_from_url("https://jobs.lever.co/palantir/abc-def")
    assert c.provider == Provider.LEVER
    assert c.identifier == "palantir"


def test_lever_api_url():
    c = detect_from_url("https://api.lever.co/v0/postings/examplecorp?mode=json")
    assert c.provider == Provider.LEVER
    assert c.identifier == "examplecorp"


def test_ashby_url():
    c = detect_from_url("https://jobs.ashbyhq.com/ramp")
    assert c.provider == Provider.ASHBY
    assert c.identifier == "ramp"


def test_workday_url_extracts_tenant_host_and_site():
    c = detect_from_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x")
    assert c.provider == Provider.WORKDAY
    assert c.identifier == "nvidia"
    assert c.extra["workday_host"] == "nvidia.wd5.myworkdayjobs.com"
    assert c.extra["workday_site"] == "NVIDIAExternalCareerSite"


def test_smartrecruiters_url():
    c = detect_from_url("https://jobs.smartrecruiters.com/Visa/744000000000-software-engineer")
    assert c.provider == Provider.SMARTRECRUITERS
    assert c.identifier == "Visa"


def test_icims_url():
    c = detect_from_url("https://careers-examplecorp.icims.com/jobs/search")
    assert c.provider == Provider.ICIMS


def test_unrelated_url_returns_none():
    assert detect_from_url("https://example.com/about") is None


def test_detect_from_html_prefers_identifier_matches():
    html = """
    <a href="https://twitter.com/examplecorp">Twitter</a>
    <a href="https://boards.greenhouse.io/examplecorp">See open roles</a>
    <script>fetch("https://api.lever.co/v0/postings/other?mode=json")</script>
    """
    candidates = detect_from_html(html)
    assert candidates
    assert candidates[0].provider == Provider.GREENHOUSE
    assert candidates[0].identifier == "examplecorp"
    assert any(c.provider == Provider.LEVER for c in candidates)
