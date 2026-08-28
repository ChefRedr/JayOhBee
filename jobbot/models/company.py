from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Provider(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    SMARTRECRUITERS = "smartrecruiters"
    ICIMS = "icims"
    ORACLE = "oracle"
    SUCCESSFACTORS = "successfactors"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class DiscoveryStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass
class Company:
    name: str
    slug: str
    careers_url: str | None = None
    jobs_url: str | None = None
    provider: Provider = Provider.UNKNOWN
    provider_identifier: str | None = None
    enabled: bool = True
    discovery_status: DiscoveryStatus = DiscoveryStatus.PENDING
    last_verified: str | None = None
    notes: str | None = None
    requires_browser: bool = False
    application_provider: str | None = None
    # workday needs both a tenant and a site name; stored as extra
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Company":
        known = {
            "name", "slug", "careers_url", "jobs_url", "provider",
            "provider_identifier", "enabled", "discovery_status",
            "last_verified", "notes", "requires_browser", "application_provider",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        if "provider" in kwargs and kwargs["provider"]:
            try:
                kwargs["provider"] = Provider(kwargs["provider"])
            except ValueError:
                kwargs["provider"] = Provider.UNKNOWN
        else:
            kwargs.pop("provider", None)
        if "discovery_status" in kwargs and kwargs["discovery_status"]:
            try:
                kwargs["discovery_status"] = DiscoveryStatus(kwargs["discovery_status"])
            except ValueError:
                kwargs["discovery_status"] = DiscoveryStatus.NEEDS_REVIEW
        else:
            kwargs.pop("discovery_status", None)
        return cls(extra=extra, **kwargs)

    def to_dict(self) -> dict:
        out: dict = {
            "name": self.name,
            "slug": self.slug,
            "careers_url": self.careers_url,
            "jobs_url": self.jobs_url,
            "provider": str(self.provider),
            "provider_identifier": self.provider_identifier,
            "enabled": self.enabled,
            "discovery_status": str(self.discovery_status),
            "last_verified": self.last_verified,
        }
        if self.notes:
            out["notes"] = self.notes
        if self.requires_browser:
            out["requires_browser"] = self.requires_browser
        if self.application_provider:
            out["application_provider"] = self.application_provider
        out.update(self.extra)
        return out

    @property
    def is_runnable(self) -> bool:
        return (
            self.enabled
            and self.discovery_status == DiscoveryStatus.VERIFIED
            and self.provider not in (Provider.UNKNOWN,)
        )
