"""Unit tests for :mod:`app.services.heritage.jangseogak`.

Network is mocked everywhere. Live-against-prod verification lives in
``tests/test_heritage_jangseogak_live.py`` and is opt-in via the
``JANGSEOGAK_LIVE_TEST=1`` env flag.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.heritage.jangseogak import (
    JANGSEOGAK_DEFAULT_BASE_URL,
    JangseogakAPIError,
    JangseogakSearchClient,
    JangseogakSearchResult,
    _parse_response,
    derive_year_and_period,
)

# ---------------------------------------------------------------------------
# derive_year_and_period — pure helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Bare 4-digit CE year, common in earlier records
        ("1670", (1670, "조선후기")),
        # CE year followed by regnal year in parentheses — the most common
        # real format observed in the live API.
        ("1903(光武 7)", (1903, "근대")),
        ("1903(光武 7) ", (1903, "근대")),  # trailing whitespace
        # Pre-임진왜란 boundary
        ("1500", (1500, "조선전기")),
        ("1593", (1593, "조선후기")),  # exact boundary year
        ("1897", (1897, "근대")),  # 대한제국 boundary
        # No year at all → empty period bucket
        ("", (None, "")),
        ("연대미상", (None, "")),
        # Year embedded mid-string (e.g. "고종 40년(1903년)") — first 4-digit
        # number wins.
        ("고종 40년(1903년) 사찬발기", (1903, "근대")),
    ],
)
def test_derive_year_and_period(raw: str, expected: tuple[int | None, str]) -> None:
    assert derive_year_and_period(raw) == expected


# ---------------------------------------------------------------------------
# _parse_response — JSON envelope → typed objects
# ---------------------------------------------------------------------------


def _live_sample_payload() -> dict[str, Any]:
    """Recreate the exact shape returned by ``/api/search`` (verified live)."""
    return {
        "header": {
            "q": "음식",
            "qw": "dataName",
            "catePath": "",
            "sortField": "",
            "sortOrder": "asc",
            "startIndex": 0,
            "pageUnit": 3,
            "totalCount": 11,
        },
        "results": [
            {
                "id": "JSG_RD01275",
                "자료명": "1903년 고종의 52세 탄일에 올린 음식과 손님에게 내린 사찬발기",
                "저자": "",
                "유형분류": "고문서/의례류/발기(發記)/사찬발기(賜饌發記)",
                "주제분류": "국왕·왕실/의례",
                "수집분류": "왕실/고문서",
                "서비스분류": "왕실고문서",
                "청구기호": "RD01275",
                "MF번호": "MF35-4659",
                "작성시기": "1903(光武 7) ",
                "출처": "장서각",
                "URL": "https://jsg.aks.ac.kr/dir/view?dataId=JSG_RD01275",
            },
            {
                "id": "JSG_RD01287",
                "자료명": "1901년 진찬도감에 내린 음식 발기",
                "저자": "",
                "유형분류": "고문서/의례류/발기(發記)/사찬발기(賜饌發記)",
                "주제분류": "국왕·왕실/의례/발기",
                "수집분류": "왕실/고문서",
                "서비스분류": "왕실고문서",
                "청구기호": "RD01287",
                "MF번호": "MF35-4659",
                "작성시기": "1901(光武 5) ",
                "출처": "장서각",
                "URL": "https://jsg.aks.ac.kr/dir/view?dataId=JSG_RD01287",
            },
            {
                "id": "JSG_RD01335",
                "자료명": "탄일진어상사찬음식발기(탄일진어상찬음식긔)",
                "저자": "",
                "유형분류": "고문서/의례류/發記進饌發記",
                "주제분류": "기타",
                "수집분류": "왕실/고문서",
                "서비스분류": "왕실고문서",
                "청구기호": "RD01335",
                "MF번호": "MF35-004659",
                "작성시기": "",
                "출처": "장서각",
                "URL": "https://jsg.aks.ac.kr/dir/view?dataId=JSG_RD01335",
            },
        ],
    }


def test_parse_response_preserves_total_and_pagination_header() -> None:
    parsed = _parse_response(_live_sample_payload())
    assert parsed.total_count == 11
    assert parsed.start_index == 0
    assert parsed.page_unit == 3
    assert len(parsed.results) == 3


def test_parse_response_maps_korean_field_names_to_dataclass_attrs() -> None:
    parsed = _parse_response(_live_sample_payload())
    first = parsed.results[0]
    assert first.external_id == "JSG_RD01275"
    assert first.title == "1903년 고종의 52세 탄일에 올린 음식과 손님에게 내린 사찬발기"
    assert first.type_category.startswith("고문서/의례류")
    assert first.subject_category == "국왕·왕실/의례"
    assert first.call_number == "RD01275"
    assert first.mf_number == "MF35-4659"
    assert first.composition_period_raw == "1903(光武 7)"
    assert first.year == 1903
    assert first.period == "근대"
    assert first.detail_url == "https://jsg.aks.ac.kr/dir/view?dataId=JSG_RD01275"


def test_parse_response_handles_missing_composition_period() -> None:
    parsed = _parse_response(_live_sample_payload())
    third = parsed.results[2]
    assert third.composition_period_raw == ""
    assert third.year is None
    assert third.period == ""


def test_parse_response_skips_non_dict_results_and_logs() -> None:
    payload: dict[str, Any] = {
        "header": {"totalCount": 1, "startIndex": 0, "pageUnit": 20},
        "results": [
            "not-a-dict",  # type: ignore[list-item]
            {"id": "JSG_OK", "자료명": "샘플"},
        ],
    }
    parsed = _parse_response(payload)
    assert len(parsed.results) == 1
    assert parsed.results[0].external_id == "JSG_OK"


def test_parse_response_drops_rows_with_no_id_and_no_title() -> None:
    payload: dict[str, Any] = {
        "header": {"totalCount": 2},
        "results": [
            {"저자": "익명"},  # no id, no 자료명 → dropped
            {"id": "JSG_KEEP", "자료명": "보존"},
        ],
    }
    parsed = _parse_response(payload)
    assert [r.external_id for r in parsed.results] == ["JSG_KEEP"]


def test_parse_response_tolerates_partial_schema_change() -> None:
    """Defensive: if upstream renames a non-essential field, we keep going."""
    payload: dict[str, Any] = {
        "header": {"totalCount": 1, "startIndex": 0, "pageUnit": 1},
        "results": [
            {
                "id": "JSG_X",
                "자료명": "테스트",
                # 저자 / 유형분류 etc all removed — should not raise
            }
        ],
    }
    parsed = _parse_response(payload)
    assert parsed.results[0].author == ""
    assert parsed.results[0].type_category == ""
    assert parsed.results[0].year is None


def test_parse_response_tolerates_malformed_header_counts() -> None:
    payload: dict[str, Any] = {
        "header": {"totalCount": "lots", "startIndex": None, "pageUnit": "many"},
        "results": [],
    }
    parsed = _parse_response(payload)
    assert parsed.total_count == 0
    assert parsed.start_index == 0
    assert parsed.page_unit == 0


# ---------------------------------------------------------------------------
# JangseogakSearchClient — request shape & error handling
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


def test_client_hits_search_endpoint_with_default_base_url() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"header": {}, "results": []})
        client.search("음식")
        url = mock_get.call_args.args[0]
        assert url == f"{JANGSEOGAK_DEFAULT_BASE_URL}/search"


def test_client_strips_trailing_slash_on_base_url() -> None:
    client = JangseogakSearchClient(base_url="https://example.test/api/")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"results": []})
        client.search("a")
        url = mock_get.call_args.args[0]
        assert url == "https://example.test/api/search"


def test_client_passes_required_query_params() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"results": []})
        client.search("음식", start_index=40, page_unit=10)
        params = mock_get.call_args.kwargs["params"]
        assert params["q"] == "음식"
        assert params["startIndex"] == 40
        assert params["pageUnit"] == 10
        assert "qw" not in params  # not provided ⇒ not sent
        assert "catePath" not in params


def test_client_passes_optional_qw_and_cate_path() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"results": []})
        client.search(
            "약과",
            search_field="dataName",
            category_path="유형분류/고문서",
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["qw"] == "dataName"
        assert params["catePath"] == "유형분류/고문서"


def test_client_caps_page_unit_at_documented_max() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"results": []})
        client.search("음식", page_unit=99999)
        params = mock_get.call_args.kwargs["params"]
        assert params["pageUnit"] == 5000


def test_client_rejects_empty_query() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="query is required"):
            client.search("")
        mock_get.assert_not_called()


def test_client_raises_api_error_on_404_with_endpoint_hint() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(404)
        with pytest.raises(JangseogakAPIError, match="endpoint may have moved"):
            client.search("음식")


def test_client_raises_api_error_on_429() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(429)
        with pytest.raises(JangseogakAPIError, match="rate limit"):
            client.search("음식")


def test_client_raises_api_error_on_500() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(503)
        mock_get.return_value.text = "service unavailable"
        with pytest.raises(JangseogakAPIError, match="503"):
            client.search("음식")


def test_client_raises_api_error_on_network_failure() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("DNS failure")):
        with pytest.raises(JangseogakAPIError, match="request failed"):
            client.search("음식")


def test_client_raises_api_error_on_non_json_body() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        bad = _mock_response(200)
        bad.json.side_effect = ValueError("not json")
        mock_get.return_value = bad
        with pytest.raises(JangseogakAPIError, match="non-JSON"):
            client.search("음식")


def test_client_returns_parsed_response_on_success() -> None:
    client = JangseogakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _live_sample_payload())
        response = client.search("음식")
        assert response.total_count == 11
        assert len(response.results) == 3
        assert isinstance(response.results[0], JangseogakSearchResult)
        assert response.results[0].year == 1903
