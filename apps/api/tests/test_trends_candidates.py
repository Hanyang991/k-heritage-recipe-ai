"""Tests for ``TrendCandidateProvider`` protocol + ``StaticCandidateProvider``."""

from __future__ import annotations

from app.services.trends.candidates import (
    StaticCandidateProvider,
    TrendCandidateProvider,
)
from app.services.trends.watchlist import DEFAULT_WATCHLIST


def test_static_provider_returns_provided_keywords() -> None:
    p = StaticCandidateProvider(["쑥라떼", "흑임자라떼"])
    assert p.discover_candidates() == ["쑥라떼", "흑임자라떼"]


def test_static_provider_defaults_to_watchlist() -> None:
    p = StaticCandidateProvider()
    assert p.discover_candidates(limit=0) == DEFAULT_WATCHLIST


def test_static_provider_respects_limit() -> None:
    p = StaticCandidateProvider(["a", "b", "c", "d", "e"])
    assert p.discover_candidates(limit=3) == ["a", "b", "c"]


def test_static_provider_returns_all_when_limit_zero() -> None:
    p = StaticCandidateProvider(["a", "b", "c"])
    assert p.discover_candidates(limit=0) == ["a", "b", "c"]


def test_static_provider_name() -> None:
    assert StaticCandidateProvider().name == "static"


def test_static_provider_does_not_mutate_input() -> None:
    keywords = ["a", "b", "c"]
    p = StaticCandidateProvider(keywords)
    out = p.discover_candidates()
    out.append("z")
    assert keywords == ["a", "b", "c"]


def test_static_provider_satisfies_protocol() -> None:
    p: TrendCandidateProvider = StaticCandidateProvider()
    assert hasattr(p, "name")
    assert callable(p.discover_candidates)
