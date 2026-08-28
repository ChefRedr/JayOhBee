import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    def load(name: str):
        return json.loads((FIXTURES / name).read_text())
    return load


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """Patch JobSource._get to serve a canned payload without network access."""
    from jobbot.sources.base import JobSource

    def install(payload):
        monkeypatch.setattr(JobSource, "_get", lambda self, url, **kw: FakeResponse(payload))

    return install
