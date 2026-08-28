from jobbot.applications.base import ApplicationAdapter
from jobbot.models.company import Provider


def get_adapter(provider: str) -> ApplicationAdapter:
    from jobbot.applications.greenhouse import GreenhouseApplicationAdapter
    from jobbot.applications.lever import LeverApplicationAdapter
    from jobbot.applications.generic import GenericApplicationAdapter

    adapters: dict[str, type[ApplicationAdapter]] = {
        Provider.GREENHOUSE: GreenhouseApplicationAdapter,
        Provider.LEVER: LeverApplicationAdapter,
    }
    cls = adapters.get(provider, GenericApplicationAdapter)
    return cls()
