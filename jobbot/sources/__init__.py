from jobbot.models.company import Provider
from jobbot.sources.base import JobSource
from jobbot.sources.greenhouse import GreenhouseSource
from jobbot.sources.lever import LeverSource
from jobbot.sources.ashby import AshbySource
from jobbot.sources.workday import WorkdaySource
from jobbot.sources.smartrecruiters import SmartRecruitersSource
from jobbot.sources.custom import CustomSource

_SOURCES: dict[Provider, type[JobSource]] = {
    Provider.GREENHOUSE: GreenhouseSource,
    Provider.LEVER: LeverSource,
    Provider.ASHBY: AshbySource,
    Provider.WORKDAY: WorkdaySource,
    Provider.SMARTRECRUITERS: SmartRecruitersSource,
    Provider.CUSTOM: CustomSource,
}


def get_source(provider: Provider) -> JobSource | None:
    cls = _SOURCES.get(provider)
    return cls() if cls else None
