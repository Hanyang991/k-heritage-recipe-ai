"""Tests for :class:`MockVectorSearchAdapter` — in-memory cosine index."""

from __future__ import annotations

import math

import pytest

from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
)
from app.services.vector_search.mock import MockVectorSearchAdapter


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _dp(
    id_: str,
    values: list[float],
    *,
    restricts: dict[str, list[str]] | None = None,
    metadata: dict[str, str] | None = None,
) -> VectorDatapoint:
    return VectorDatapoint(
        datapoint_id=id_,
        values=values,
        restricts=restricts or {},
        metadata=metadata or {},
    )


def test_mock_adapter_requires_at_least_one_namespace() -> None:
    with pytest.raises(ValueError, match="at least one namespace"):
        MockVectorSearchAdapter(namespaces=[])


def test_mock_adapter_known_namespaces_preserves_order() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak", "koreanstudies", "nlk"])
    assert a.known_namespaces() == ["jangseogak", "koreanstudies", "nlk"]


def test_mock_adapter_upsert_and_query_isolated_per_namespace() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak", "nlk"])
    js_vec = _unit([1.0, 0.0, 0.0])
    nlk_vec = _unit([0.0, 1.0, 0.0])
    a.upsert("jangseogak", [_dp("jsg:1", js_vec)])
    a.upsert("nlk", [_dp("nlk:1", nlk_vec)])

    # Querying jsg with the jsg vector returns the jsg entry only.
    jsg_results = a.query("jangseogak", js_vec, top_k=5)
    assert [m.datapoint_id for m in jsg_results] == ["jsg:1"]
    assert math.isclose(jsg_results[0].score, 1.0, abs_tol=1e-9)

    # Querying nlk with the same jsg vector returns nlk's content
    # (orthogonal → near-zero similarity), not the jsg entry.
    nlk_results = a.query("nlk", js_vec, top_k=5)
    assert [m.datapoint_id for m in nlk_results] == ["nlk:1"]
    assert nlk_results[0].score == 0.0


def test_mock_adapter_upsert_is_idempotent_by_datapoint_id() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert("jangseogak", [_dp("jsg:1", _unit([1.0, 0.0]))])
    a.upsert("jangseogak", [_dp("jsg:1", _unit([0.0, 1.0]))])
    # Second upsert replaces the first — querying with [0,1] returns 1.0.
    results = a.query("jangseogak", _unit([0.0, 1.0]), top_k=5)
    assert len(results) == 1
    assert results[0].datapoint_id == "jsg:1"
    assert math.isclose(results[0].score, 1.0, abs_tol=1e-9)


def test_mock_adapter_query_unknown_namespace_raises() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    with pytest.raises(VectorIndexNotConfiguredError):
        a.query("unknown", [1.0, 0.0], top_k=1)


def test_mock_adapter_upsert_unknown_namespace_raises() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    with pytest.raises(VectorIndexNotConfiguredError):
        a.upsert("unknown", [_dp("x:1", [1.0, 0.0])])


def test_mock_adapter_query_returns_top_k_sorted_by_similarity() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert(
        "jangseogak",
        [
            _dp("a", _unit([1.0, 0.0])),
            _dp("b", _unit([0.9, 0.1])),
            _dp("c", _unit([0.5, 0.5])),
            _dp("d", _unit([0.0, 1.0])),
        ],
    )
    results = a.query("jangseogak", _unit([1.0, 0.0]), top_k=3)
    assert [m.datapoint_id for m in results] == ["a", "b", "c"]
    assert results[0].score > results[1].score > results[2].score


def test_mock_adapter_query_clamps_score_to_unit_range() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    # Anti-parallel unit vectors produce cosine = -1.0 ; mock clamps to 0.
    a.upsert("jangseogak", [_dp("a", [-1.0, 0.0])])
    results = a.query("jangseogak", [1.0, 0.0], top_k=1)
    assert results[0].score == 0.0


def test_mock_adapter_query_filters_by_restricts() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert(
        "jangseogak",
        [
            _dp("joseon", _unit([1.0, 0.0]), restricts={"period": ["조선후기"]}),
            _dp("goryeo", _unit([1.0, 0.0]), restricts={"period": ["고려"]}),
        ],
    )
    results = a.query("jangseogak", _unit([1.0, 0.0]), top_k=5, restricts={"period": ["조선후기"]})
    assert [m.datapoint_id for m in results] == ["joseon"]


def test_mock_adapter_restrict_with_no_match_returns_empty() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert(
        "jangseogak",
        [_dp("joseon", _unit([1.0, 0.0]), restricts={"period": ["조선후기"]})],
    )
    results = a.query(
        "jangseogak",
        _unit([1.0, 0.0]),
        top_k=5,
        restricts={"period": ["고려"]},
    )
    assert results == []


def test_mock_adapter_query_with_top_k_zero_returns_empty() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert("jangseogak", [_dp("a", [1.0, 0.0])])
    assert a.query("jangseogak", [1.0, 0.0], top_k=0) == []


def test_mock_adapter_query_empty_namespace_returns_empty() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    assert a.query("jangseogak", [1.0, 0.0], top_k=3) == []


def test_mock_adapter_query_dimension_mismatch_raises() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert("jangseogak", [_dp("a", [1.0, 0.0, 0.0])])
    with pytest.raises(ValueError, match="dimension mismatch"):
        a.query("jangseogak", [1.0, 0.0], top_k=1)


def test_mock_adapter_returns_metadata_in_match() -> None:
    a = MockVectorSearchAdapter(namespaces=["jangseogak"])
    a.upsert(
        "jangseogak",
        [
            _dp(
                "a",
                _unit([1.0, 0.0]),
                metadata={"title": "음식디미방", "year": "1670"},
            )
        ],
    )
    results = a.query("jangseogak", _unit([1.0, 0.0]), top_k=1)
    assert results[0].metadata == {"title": "음식디미방", "year": "1670"}
