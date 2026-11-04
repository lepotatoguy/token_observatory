from typing import Annotated

from pydantic import Field

from backend.models.base import Model


class LimitWindow(Model):
    id: str | None = None
    used_percent: Annotated[float, Field(ge=0)] | None = None
    window_minutes: Annotated[int, Field(ge=0)] | None = None
    resets_at: float | None = None


class RateLimits(Model):
    primary: LimitWindow | None = None
    secondary: LimitWindow | None = None
    observed_at: float | None = None
    limit_id: str | None = None
    source: str | None = None


class LiveLimits(Model):
    checked_at: float | None = None
    errors: dict[str, str] = Field(default_factory=dict)
    claude: RateLimits | None = None
    codex: RateLimits | None = None
