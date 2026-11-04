from typing import Annotated, Any

from pydantic import Field

from backend.models.base import Model
from backend.models.limits import LiveLimits, RateLimits
from backend.models.session import Session


Price = Annotated[float, Field(ge=0)]


class PriceEntry(Model):
    match: str
    rates: Annotated[list[Price | None], Field(min_length=5, max_length=5)]
    long_rates: Annotated[list[Price | None], Field(min_length=5, max_length=5)] | None = None
    estimated: bool = False
    custom: bool = False


class PricingSnapshot(Model):
    models: list[PriceEntry]
    fetched_at: float | None = None
    source: str
    error: str | None = None


class ArchiveManifest(Model):
    directory: str
    saved_at: float | None
    interval_seconds: Annotated[int, Field(ge=0)]
    dates: list[str]
    error: str | None


class SnapshotProviders(Model):
    enabled: list[str]
    setup_done: bool


class UsageSnapshot(Model):
    at: float
    sessions: list[Session]
    sources: list[dict[str, Any]]
    warnings: list[str]
    limits: dict[str, RateLimits]
    accounting_version: Annotated[int, Field(ge=0)]
    providers: SnapshotProviders
    live_limits: LiveLimits
    archive: ArchiveManifest | None = None
    limit_control: dict[str, Any]
