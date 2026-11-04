from typing import Annotated, Any

from pydantic import Field

from backend.models.base import Model


TokenCount = Annotated[int, Field(ge=0)]


class TokenEvent(Model):
    at: float | None
    model: str
    input: TokenCount
    cached: TokenCount
    write: TokenCount
    output: TokenCount
    reasoning: TokenCount
    write_1h: TokenCount = 0
    cache_unreported: bool = False


class SessionTotals(Model):
    input: TokenCount
    cached: TokenCount
    write: TokenCount
    output: TokenCount
    reasoning: TokenCount
    total: TokenCount


class Session(Model):
    id: str
    session_id: str
    conversation_id: str
    provider: str
    title: str
    project: str | None
    model: str
    models: list[str]
    last: float | None
    modified: float
    subagent: bool
    parent: str | None
    totals: SessionTotals
    events: list[TokenEvent]
    context: TokenCount | None
    capacity: TokenCount | None
    capacity_source: str | None
    compactions: TokenCount
    rate_limits: dict[str, Any] | None
    rate_limits_at: float | None
    reported_cost: Annotated[float, Field(ge=0)] | None
    source: str
    parse_errors: TokenCount
    usage_source: str
    latest_usage: dict[str, Any] | None
    latest_usage_at: float | None
