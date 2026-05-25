"""Tests for :class:`VertexAIVectorSearchAdapter` and the live factory branch."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.vector_search import get_vector_search_adapter
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
)
from app.services.vector_search.mock import MockVectorSearchAdapter
from app.services.vector_search.vertex import (
    VectorIndexConfig,
    VertexAIVectorSearchAdapter,
    VertexVectorSearchAPIError,
    _parse_neighbors,
    _serialize_datapoint,
)


def _make_response(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(body, str):
        resp.text = body
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.text = json.dumps(body)
        resp.json = MagicMock(return_value=body)
    return resp


def _config(name: str) -> VectorIndexConfig:
    return VectorIndexConfig(
        index_id=f"idx-{name}",
        deployed_index_id=f"dep-{name}",
        endpoint_id=f"ep-{name}",
        endpoint_host=f"{name}.us-central1-12345.vdb.vertexai.goog",
    )


def _adapter(index_configs: dict[str, VectorIndexConfig]) -> VertexAIVectorSearchAdapter:
    return VertexAIVectorSearchAdapter(
        project_id="proj",
        location="us-central1",
        index_configs=index_configs,
        token_provider=lambda: "tok",
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_adapter_rejects_empty_project_id() -> None:
    with pytest.raises(ValueError, match="VERTEX_PROJECT_ID is required"):
        VertexAIVectorSearchAdapter(
            project_id="",
            index_configs={"jangseogak": _config("jsg")},
            token_provider=lambda: "tok",
        )


def test_adapter_rejects_empty_index_configs() -> None:
    with pytest.raises(ValueError, match="at least one index_config"):
        VertexAIVectorSearchAdapter(
            project_id="proj",
            index_configs={},
            token_provider=lambda: "tok",
        )


def test_adapter_rejects_non_positive_upsert_batch() -> None:
    with pytest.raises(ValueError, match="upsert_batch_size must be positive"):
        VertexAIVectorSearchAdapter(
            project_id="proj",
            index_configs={"jangseogak": _config("jsg")},
            token_provider=lambda: "tok",
            upsert_batch_size=0,
        )


def test_adapter_known_namespaces_sorted() -> None:
    adapter = _adapter(
        {
            "nlk": _config("nlk"),
            "jangseogak": _config("jsg"),
            "koreanstudies": _config("ks"),
        }
    )
    assert adapter.known_namespaces() == ["jangseogak", "koreanstudies", "nlk"]


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def test_upsert_routes_to_namespace_specific_index() -> None:
    adapter = _adapter(
        {
            "jangseogak": _config("jsg"),
            "koreanstudies": _config("ks"),
        }
    )
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, {})
        adapter.upsert(
            "koreanstudies",
            [VectorDatapoint(datapoint_id="ks:1", values=[0.1, 0.2])],
        )
    url = client.post.call_args.args[0]
    # Must route to ``idx-ks`` not ``idx-jsg``.
    assert "/indexes/idx-ks:upsertDatapoints" in url
    assert "us-central1-aiplatform.googleapis.com" in url
    body = client.post.call_args.kwargs["json"]
    assert body == {"datapoints": [{"datapointId": "ks:1", "featureVector": [0.1, 0.2]}]}


def test_upsert_serializes_restricts_in_vertex_wire_format() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, {})
        adapter.upsert(
            "jangseogak",
            [
                VectorDatapoint(
                    datapoint_id="jsg:1",
                    values=[0.1, 0.2],
                    restricts={"period": ["조선후기"], "region": ["충청"]},
                )
            ],
        )
    body = client.post.call_args.kwargs["json"]
    restricts = body["datapoints"][0]["restricts"]
    assert {"namespace": "period", "allowList": ["조선후기"]} in restricts
    assert {"namespace": "region", "allowList": ["충청"]} in restricts


def test_upsert_chunks_batches() -> None:
    adapter = VertexAIVectorSearchAdapter(
        project_id="proj",
        index_configs={"jangseogak": _config("jsg")},
        token_provider=lambda: "tok",
        upsert_batch_size=2,
    )
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, {})
        adapter.upsert(
            "jangseogak",
            [VectorDatapoint(datapoint_id=f"jsg:{i}", values=[0.1, 0.2]) for i in range(5)],
        )
    assert client.post.call_count == 3
    # Last call should have only one datapoint.
    last_body = client.post.call_args_list[-1].kwargs["json"]
    assert len(last_body["datapoints"]) == 1


def test_upsert_unknown_namespace_raises() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with pytest.raises(VectorIndexNotConfiguredError):
        adapter.upsert("unknown", [VectorDatapoint(datapoint_id="x:1", values=[0.1])])


def test_upsert_empty_datapoints_no_request() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        adapter.upsert("jangseogak", [])
    client.post.assert_not_called()


def test_upsert_raises_on_non_200() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(500, {"error": "oops"})
        with pytest.raises(VertexVectorSearchAPIError, match="500"):
            adapter.upsert(
                "jangseogak",
                [VectorDatapoint(datapoint_id="jsg:1", values=[0.1, 0.2])],
            )


def test_upsert_raises_on_transport_error() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.ConnectError("dns")
        with pytest.raises(VertexVectorSearchAPIError, match="transport"):
            adapter.upsert(
                "jangseogak",
                [VectorDatapoint(datapoint_id="jsg:1", values=[0.1, 0.2])],
            )


def test_upsert_raises_on_empty_token() -> None:
    adapter = VertexAIVectorSearchAdapter(
        project_id="proj",
        index_configs={"jangseogak": _config("jsg")},
        token_provider=lambda: "",
    )
    with pytest.raises(VertexVectorSearchAPIError, match="empty token"):
        adapter.upsert(
            "jangseogak",
            [VectorDatapoint(datapoint_id="jsg:1", values=[0.1, 0.2])],
        )


# ---------------------------------------------------------------------------
# Query / findNeighbors
# ---------------------------------------------------------------------------


def _neighbors_payload(items: list[tuple[str, float]]) -> dict:
    return {
        "nearestNeighbors": [
            {
                "id": "q0",
                "neighbors": [
                    {
                        "datapoint": {"datapointId": dp_id},
                        "distance": distance,
                    }
                    for dp_id, distance in items
                ],
            }
        ]
    }


def test_query_targets_endpoint_host_not_global() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, _neighbors_payload([("jsg:1", 0.0)]))
        results = adapter.query("jangseogak", [0.1, 0.2], top_k=3)
    url = client.post.call_args.args[0]
    assert "jsg.us-central1-12345.vdb.vertexai.goog" in url
    assert "/indexEndpoints/ep-jsg:findNeighbors" in url
    # Body wiring.
    body = client.post.call_args.kwargs["json"]
    assert body["deployedIndexId"] == "dep-jsg"
    assert body["queries"][0]["datapoint"]["featureVector"] == [0.1, 0.2]
    assert body["queries"][0]["neighborCount"] == 3
    # Score normalisation.
    assert results[0].datapoint_id == "jsg:1"
    assert pytest.approx(results[0].score) == 1.0


def test_query_sends_restricts_in_vertex_wire_format() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, _neighbors_payload([]))
        adapter.query(
            "jangseogak",
            [0.1, 0.2],
            top_k=3,
            restricts={"period": ["조선후기"]},
        )
    body = client.post.call_args.kwargs["json"]
    dp = body["queries"][0]["datapoint"]
    assert dp["restricts"] == [{"namespace": "period", "allowList": ["조선후기"]}]


def test_query_normalises_distance_to_similarity() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(
            200,
            _neighbors_payload(
                [
                    ("perfect", 0.0),  # → score 1.0
                    ("halfway", 1.0),  # → score 0.5
                    ("opposite", 2.0),  # → score 0.0
                    ("clamp_below", 3.0),  # → clamped to 0.0
                    ("clamp_above", -1.0),  # → clamped to 1.0
                ]
            ),
        )
        results = adapter.query("jangseogak", [0.1, 0.2], top_k=5)
    # Sorted highest score first; clamp_above ties perfect (both 1.0).
    scores = {m.datapoint_id: m.score for m in results}
    assert scores["perfect"] == 1.0
    assert pytest.approx(scores["halfway"]) == 0.5
    assert scores["opposite"] == 0.0
    assert scores["clamp_below"] == 0.0
    assert scores["clamp_above"] == 1.0


def test_query_top_k_zero_returns_empty_without_request() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        results = adapter.query("jangseogak", [0.1, 0.2], top_k=0)
    client.post.assert_not_called()
    assert results == []


def test_query_unknown_namespace_raises() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with pytest.raises(VectorIndexNotConfiguredError):
        adapter.query("unknown", [0.1, 0.2], top_k=3)


def test_query_returns_empty_when_no_nearest_neighbors() -> None:
    adapter = _adapter({"jangseogak": _config("jsg")})
    with patch("app.services.vector_search.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, {})
        results = adapter.query("jangseogak", [0.1, 0.2], top_k=3)
    assert results == []


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_neighbors_missing_datapoint_id_raises() -> None:
    with pytest.raises(VertexVectorSearchAPIError, match="datapointId"):
        _parse_neighbors({"nearestNeighbors": [{"neighbors": [{"datapoint": {}}]}]})


def test_parse_neighbors_missing_datapoint_object_raises() -> None:
    with pytest.raises(VertexVectorSearchAPIError, match="missing 'datapoint'"):
        _parse_neighbors({"nearestNeighbors": [{"neighbors": [{}]}]})


def test_parse_neighbors_non_numeric_distance_raises() -> None:
    with pytest.raises(VertexVectorSearchAPIError, match="non-numeric"):
        _parse_neighbors(
            {
                "nearestNeighbors": [
                    {
                        "neighbors": [
                            {
                                "datapoint": {"datapointId": "x"},
                                "distance": "not-a-number",
                            }
                        ]
                    }
                ]
            }
        )


def test_serialize_datapoint_round_trip() -> None:
    dp = VectorDatapoint(
        datapoint_id="jsg:1",
        values=[0.1, 0.2, 0.3],
        restricts={"period": ["조선후기"], "region": ["충청"]},
    )
    body = _serialize_datapoint(dp)
    assert body["datapointId"] == "jsg:1"
    assert body["featureVector"] == [0.1, 0.2, 0.3]
    namespaces = {r["namespace"] for r in body["restricts"]}
    assert namespaces == {"period", "region"}


def test_serialize_datapoint_without_restricts_omits_field() -> None:
    dp = VectorDatapoint(datapoint_id="x", values=[1.0])
    body = _serialize_datapoint(dp)
    assert "restricts" not in body


# ---------------------------------------------------------------------------
# Factory degrade behaviour
# ---------------------------------------------------------------------------


def test_factory_returns_mock_when_provider_is_mock(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "mock")
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, MockVectorSearchAdapter)


def test_factory_degrades_when_project_missing(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "live")
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    assert isinstance(adapter, MockVectorSearchAdapter)


def test_factory_degrades_when_token_missing(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "live")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj")
    monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
        monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    assert isinstance(adapter, MockVectorSearchAdapter)


def test_factory_degrades_when_no_namespace_fully_configured(
    monkeypatch,
) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "live")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    # No VERTEX_VECTOR_INDEX_* env vars set.
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
        monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    assert isinstance(adapter, MockVectorSearchAdapter)


def test_factory_skips_namespace_with_partial_envs(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_vector_search_adapter.cache_clear()
    monkeypatch.setenv("VECTOR_SEARCH_PROVIDER", "live")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    # Only jangseogak has the full bundle; koreanstudies is missing endpoint host.
    monkeypatch.setenv("VERTEX_VECTOR_INDEX_ID_JANGSEOGAK", "idx-jsg")
    monkeypatch.setenv("VERTEX_VECTOR_DEPLOYED_INDEX_ID_JANGSEOGAK", "dep-jsg")
    monkeypatch.setenv("VERTEX_VECTOR_INDEX_ENDPOINT_ID_JANGSEOGAK", "ep-jsg")
    monkeypatch.setenv(
        "VERTEX_VECTOR_INDEX_ENDPOINT_HOST_JANGSEOGAK",
        "jsg.us-central1-12345.vdb.vertexai.goog",
    )
    monkeypatch.setenv("VERTEX_VECTOR_INDEX_ID_KOREANSTUDIES", "idx-ks")
    # Intentionally missing the other 3 koreanstudies vars.
    try:
        adapter = get_vector_search_adapter()
    finally:
        get_settings.cache_clear()
        get_vector_search_adapter.cache_clear()
    assert isinstance(adapter, VertexAIVectorSearchAdapter)
    # Only jangseogak survived the partial-env filter.
    assert adapter.known_namespaces() == ["jangseogak"]
