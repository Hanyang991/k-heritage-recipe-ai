"""Trend keyword schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class TrendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    keyword: str
    region: str
    change_percent: float
    is_up: bool
    week_of: date


class TrendRefreshResponse(BaseModel):
    week_of: date | None
    inserted: int
    updated: int


class TrendSeriesPoint(BaseModel):
    period: date
    ratio: float


class TrendSeriesOut(BaseModel):
    keyword: str
    time_unit: str
    points: list[TrendSeriesPoint]


class TrendDebugProviderRow(BaseModel):
    """Per-provider gather diagnostics for ``GET /v1/admin/trends/debug``."""

    name: str
    candidate_count: int
    candidates_sample: list[str]
    elapsed_ms: int
    error: str | None = None


class TrendDebugRankedRow(BaseModel):
    """One ranked keyword in the merged output, with all source attributions."""

    keyword: str
    score: float
    primary_source: str
    all_sources: list[str]
    current_ratio: float | None = None
    rise_percent: float | None = None


class TrendDebugResponse(BaseModel):
    """Admin-only snapshot of the discovery pipeline for one ``today``.

    Always returns ``providers`` and ``ranked`` so the same shape works for
    every value of ``TRENDS_DISCOVERY_SOURCE``; the simpler curated /
    shopping_insight sources just report a single provider row.
    """

    discovery_type: str
    ref_date: date
    limit: int
    unique_candidate_count: int
    scored_count: int
    providers: list[TrendDebugProviderRow]
    ranked: list[TrendDebugRankedRow]
