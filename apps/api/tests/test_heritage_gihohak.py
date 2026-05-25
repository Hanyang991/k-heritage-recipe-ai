"""Unit tests for :mod:`app.services.heritage.gihohak`.

Network is mocked everywhere — the live adapter is exercised by
``test_heritage_live_gihohak_adapter.py``. The XML samples below mirror
the response shape documented at <http://giho.cnu.ac.kr/apiInfo.do>
and observed live via the Internet Archive Wayback Machine.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.heritage.gihohak import (
    GIHOHAK_DEFAULT_BASE_URL,
    GihohakAPIError,
    GihohakSearchClient,
    GihohakSearchResult,
    _parse_response,
    derive_year_and_period,
)

# ---------------------------------------------------------------------------
# derive_year_and_period — pure helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1631", (1631, "조선후기")),
        ("1500", (1500, "조선전기")),
        ("1592", (1592, "조선전기")),  # 1592 is still 조선전기 (< 1593 boundary)
        ("1593", (1593, "조선후기")),
        ("1896", (1896, "조선후기")),
        ("1897", (1897, "근대")),
        ("1900", (1900, "근대")),
        ("미상", (None, "")),
        ("0", (None, "")),
        ("", (None, "")),
        # The docs say integer, but the live data sometimes wraps it in a
        # human phrase. We extract a 4-digit year if present, else degrade.
        ("辛酉(1801)", (1801, "조선후기")),
        ("기축(1889년)", (1889, "조선후기")),
        # No 4-digit year → unknown
        ("순조 14년", (None, "")),
    ],
)
def test_derive_year_and_period(raw: str, expected: tuple[int | None, str]) -> None:
    assert derive_year_and_period(raw) == expected


# ---------------------------------------------------------------------------
# _parse_response — XML envelope → typed objects
# ---------------------------------------------------------------------------


_LIVE_SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<gihoConfucianism>
  <searchInfo>
    <total>3772</total>
    <type>OD</type>
    <target>all</target>
    <keyword>간찰</keyword>
    <page>1</page>
    <pageSize>3</pageSize>
  </searchInfo>
  <searchResult>
    <literature>
      <identifier>OD_20131231000002_68</identifier>
      <dataType>OD</dataType>
      <dataTypeNm>고문서</dataTypeNm>
      <mainTitle><![CDATA[10월4일에 이인조(李寅祖)가 연재(淵齋) 송병선(宋秉璿)댁에 보낸 간찰(簡札)]]></mainTitle>
      <alternativeTitle><![CDATA[簡札]]></alternativeTitle>
      <mainCreator><![CDATA[이인조[李寅祖]]]></mainCreator>
      <created>미상</created>
      <relationDate><![CDATA[미상]]></relationDate>
      <recomFg>N</recomFg>
      <classFullNm>서간통고류&gt;서간류&gt;간찰</classFullNm>
      <uci><![CDATA[G001+KR03-7001144.131231.D0.OD_20131231000002_68]]></uci>
      <url><![CDATA[http://giho.cnu.ac.kr/shr/gihoSearchUserDetail.do?data_type=OD&identifier=OD_20131231000002_68]]></url>
      <abstract><![CDATA[모년(1885년 이후) 10월 4일에 보령의 외사촌 이인조가 원계의 송병선에게 보낸 편지.]]></abstract>
    </literature>
    <literature>
      <identifier>OB_18910101000000_01</identifier>
      <dataType>OB</dataType>
      <dataTypeNm>고서</dataTypeNm>
      <mainTitle><![CDATA[음식방문]]></mainTitle>
      <alternativeTitle><![CDATA[飮食方文]]></alternativeTitle>
      <mainCreator><![CDATA[송시열(宋時烈)]]></mainCreator>
      <created>1670</created>
      <relationDate><![CDATA[경술]]></relationDate>
      <recomFg>Y</recomFg>
      <classFullNm>잡저류&gt;음식류</classFullNm>
      <uci><![CDATA[G001+KR03-7001144.180101.B0.OB_18910101000000_01]]></uci>
      <url><![CDATA[http://giho.cnu.ac.kr/shr/gihoSearchUserDetail.do?data_type=OB&identifier=OB_18910101000000_01]]></url>
      <abstract><![CDATA[송시열 문중에 전해온 음식 조리법 모음.]]></abstract>
    </literature>
    <literature>
      <identifier></identifier>
      <mainTitle></mainTitle>
      <dataType>OD</dataType>
    </literature>
  </searchResult>
</gihoConfucianism>"""


def test_parse_response_preserves_search_info_header() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    assert parsed.total_count == 3772
    assert parsed.type_filter == "OD"
    assert parsed.target == "all"
    assert parsed.keyword == "간찰"
    assert parsed.page == 1
    assert parsed.page_size == 3
    # 3rd item is dropped (no identifier AND no title), so 2 remain.
    assert len(parsed.results) == 2


def test_parse_response_maps_xml_tags_to_dataclass_attrs() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    first = parsed.results[0]
    assert first.external_id == "OD_20131231000002_68"
    assert first.data_type == "OD"
    assert first.data_type_name == "고문서"
    assert "간찰" in first.title
    assert first.alt_title == "簡札"
    assert "이인조" in first.creator
    assert first.created_raw == "미상"
    assert first.year is None
    assert first.period == ""
    assert first.relation_date == "미상"
    assert first.recommended is False
    assert first.class_full_name == "서간통고류>서간류>간찰"
    assert first.uci.startswith("G001+KR03-")
    assert first.detail_url.startswith("http://giho.cnu.ac.kr/shr/")
    assert "보령" in first.abstract


def test_parse_response_parses_numeric_created_year() -> None:
    """The second item has ``<created>1670</created>`` — must bucket as 조선후기."""
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    second = parsed.results[1]
    assert second.external_id == "OB_18910101000000_01"
    assert second.data_type == "OB"
    assert second.data_type_name == "고서"
    assert second.title == "음식방문"
    assert second.alt_title == "飮食方文"
    assert second.year == 1670
    assert second.period == "조선후기"
    assert second.relation_date == "경술"
    assert second.recommended is True
    assert "음식류" in second.class_full_name


def test_parse_response_skips_items_missing_both_id_and_title() -> None:
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchInfo>
        <total>2</total><type>OB</type><target>all</target>
        <keyword>음식</keyword><page>1</page><pageSize>10</pageSize>
      </searchInfo>
      <searchResult>
        <literature><dataType>OB</dataType></literature>
        <literature>
          <identifier>OB_KEEP</identifier>
          <mainTitle><![CDATA[샘플 고서]]></mainTitle>
          <dataType>OB</dataType>
        </literature>
      </searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert [r.external_id for r in parsed.results] == ["OB_KEEP"]


def test_parse_response_keeps_item_with_id_only() -> None:
    """Identifier alone is enough — we don't need a title to retain a row."""
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchInfo>
        <total>1</total><type>OB</type><target>all</target>
        <keyword>음식</keyword><page>1</page><pageSize>10</pageSize>
      </searchInfo>
      <searchResult>
        <literature>
          <identifier>OB_ID_ONLY</identifier>
        </literature>
      </searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert len(parsed.results) == 1
    assert parsed.results[0].external_id == "OB_ID_ONLY"
    assert parsed.results[0].title == ""


def test_parse_response_normalises_null_keyword_marker() -> None:
    """Upstream encodes a missing keyword as the literal string ``null``."""
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchInfo>
        <total>0</total><type>OB</type><target>all</target>
        <keyword>null</keyword><page>1</page><pageSize>10</pageSize>
      </searchInfo>
      <searchResult></searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert parsed.keyword == ""


def test_parse_response_tolerates_malformed_header_counts() -> None:
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchInfo>
        <total>not-a-number</total><type></type><target>all</target>
        <keyword>음식</keyword><page></page><pageSize>many</pageSize>
      </searchInfo>
      <searchResult></searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert parsed.total_count == 0
    assert parsed.page == 1
    assert parsed.page_size == 0
    assert parsed.results == ()


def test_parse_response_tolerates_missing_search_info_wrapper() -> None:
    """Defensive: if upstream drops <searchInfo> entirely we still parse rows."""
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchResult>
        <literature>
          <identifier>OB_ROBUST</identifier>
          <mainTitle><![CDATA[탄력 테스트]]></mainTitle>
        </literature>
      </searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert parsed.total_count == 0
    assert parsed.page == 1
    assert [r.external_id for r in parsed.results] == ["OB_ROBUST"]


def test_parse_response_tolerates_partial_schema_change() -> None:
    """If upstream drops non-essential elements we keep going."""
    xml = """<?xml version="1.0"?>
    <gihoConfucianism>
      <searchInfo>
        <total>1</total><type>OB</type><target>all</target>
        <keyword>x</keyword><page>1</page><pageSize>1</pageSize>
      </searchInfo>
      <searchResult>
        <literature>
          <identifier>UCI_X</identifier>
          <mainTitle>테스트</mainTitle>
        </literature>
      </searchResult>
    </gihoConfucianism>"""
    parsed = _parse_response(xml)
    assert parsed.results[0].external_id == "UCI_X"
    assert parsed.results[0].creator == ""
    assert parsed.results[0].year is None
    assert parsed.results[0].period == ""
    assert parsed.results[0].recommended is False


def test_parse_response_raises_on_non_xml() -> None:
    with pytest.raises(GihohakAPIError, match="non-XML"):
        _parse_response("<<<not xml>>>")


def test_parse_response_raises_on_unexpected_root() -> None:
    with pytest.raises(GihohakAPIError, match="unexpected root"):
        _parse_response("<root><foo/></root>")


# ---------------------------------------------------------------------------
# GihohakSearchClient — request shape & error handling
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    return resp


def test_client_hits_search_endpoint_with_default_base_url() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("간찰")
        url = mock_get.call_args.args[0]
        assert url == f"{GIHOHAK_DEFAULT_BASE_URL}/api/literature/search.do"


def test_client_strips_trailing_slash_on_base_url() -> None:
    client = GihohakSearchClient(base_url="http://example.test/giho/")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("간찰")
        url = mock_get.call_args.args[0]
        assert url == "http://example.test/giho/api/literature/search.do"


def test_client_passes_required_default_params() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("간찰")
        params = mock_get.call_args.kwargs["params"]
        # Default heritage adapter uses 고서 + cross-field search.
        assert params["type"] == "OB"
        assert params["target"] == "all"
        assert params["keyword"] == "간찰"
        assert params["page"] == 1
        assert params["pageSize"] == 10


def test_client_passes_explicit_pagination_and_filters() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search(
            "음식",
            type_filter="OD",
            target="title",
            page=2,
            page_size=25,
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["type"] == "OD"
        assert params["target"] == "title"
        assert params["page"] == 2
        assert params["pageSize"] == 25


def test_client_caps_page_size_at_safe_maximum() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", page_size=99999)
        params = mock_get.call_args.kwargs["params"]
        assert params["pageSize"] == 100


def test_client_normalises_negative_page() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", page=-3)
        params = mock_get.call_args.kwargs["params"]
        assert params["page"] == 1


def test_client_rejects_empty_query() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="query is required"):
            client.search("")
        mock_get.assert_not_called()


def test_client_rejects_unknown_type_filter() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="type_filter"):
            client.search("음식", type_filter="ZZ")
        mock_get.assert_not_called()


def test_client_rejects_unknown_target() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="target"):
            client.search("음식", target="zzz")
        mock_get.assert_not_called()


def test_client_raises_api_error_on_404_with_endpoint_hint() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(404, "")
        with pytest.raises(GihohakAPIError, match="endpoint may have moved"):
            client.search("음식")


def test_client_raises_api_error_on_429() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(429, "")
        with pytest.raises(GihohakAPIError, match="rate limit"):
            client.search("음식")


def test_client_raises_api_error_on_500() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(503, "service unavailable")
        with pytest.raises(GihohakAPIError, match="503"):
            client.search("음식")


def test_client_raises_api_error_on_network_failure() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("DNS failure")):
        with pytest.raises(GihohakAPIError, match="request failed"):
            client.search("음식")


def test_client_raises_api_error_on_non_xml_body() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, "<html>error</html>")
        with pytest.raises(GihohakAPIError, match="unexpected root|non-XML"):
            client.search("음식")


def test_client_returns_parsed_response_on_success() -> None:
    client = GihohakSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        resp = client.search("간찰", type_filter="OD")
        assert resp.total_count == 3772
        assert len(resp.results) == 2
        assert all(isinstance(r, GihohakSearchResult) for r in resp.results)
