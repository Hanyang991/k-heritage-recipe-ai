"""Unit tests for :mod:`app.services.heritage.nlk`.

Network is mocked everywhere — the live adapter is exercised by
``test_heritage_live_nlk_adapter.py``. The XML samples below mirror the
response shape documented at <https://www.nl.go.kr/NL/contents/N31101030700.do>.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.heritage.nlk import (
    NLK_DEFAULT_BASE_URL,
    NlkAPIError,
    NlkSearchClient,
    NlkSearchResult,
    _parse_response,
    derive_year_and_period,
)

# ---------------------------------------------------------------------------
# derive_year_and_period — pure helper (shared logic with 장서각/한국학자료포털)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2012", (2012, "근대")),
        ("201201", (2012, "근대")),
        ("1670", (1670, "조선후기")),
        ("1500", (1500, "조선전기")),
        ("1593", (1593, "조선후기")),
        ("1897", (1897, "근대")),
        ("", (None, "")),
        ("연대미상", (None, "")),
        ("순조 14년(1814년)", (1814, "조선후기")),
        ("정조 즉위년(1776년)", (1776, "조선후기")),
        # NLK 고문헌 records sometimes encode the era as a pure regnal year
        # (no CE digits) — we degrade to (None, "") rather than guess.
        ("순조 14년", (None, "")),
    ],
)
def test_derive_year_and_period(raw: str, expected: tuple[int | None, str]) -> None:
    assert derive_year_and_period(raw) == expected


# ---------------------------------------------------------------------------
# _parse_response — XML envelope → typed objects
# ---------------------------------------------------------------------------


_LIVE_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<channel>
  <kwd>토지</kwd>
  <total>1234</total>
  <pageNum>1</pageNum>
  <pageSize>3</pageSize>
  <list>
    <item>
      <title_info>토지</title_info>
      <author_info>박경리 지음</author_info>
      <pub_info>마로니에북스</pub_info>
      <pub_year_info>2012</pub_year_info>
      <type_name>도서</type_name>
      <type_code>11</type_code>
      <control_no>KMO201234567890</control_no>
      <call_no>813.6-박52토</call_no>
      <isbn>9788984993727</isbn>
      <doc_yn>N</doc_yn>
      <org_link></org_link>
      <detail_link>/NL/contents/search.do?id=KMO201234567890</detail_link>
      <id>internal-1</id>
      <kdc_code_1s>800</kdc_code_1s>
      <kdc_name_1s>문학</kdc_name_1s>
      <lic_yn>L</lic_yn>
      <lic_text>국립중앙도서관 무료 열람</lic_text>
      <reg_date>20120101</reg_date>
    </item>
    <item>
      <title_info>음식디미방</title_info>
      <author_info>장계향</author_info>
      <pub_info>경상도 석계종가</pub_info>
      <pub_year_info>순조 14년(1814년)</pub_year_info>
      <type_name>고문헌</type_name>
      <type_code>13</type_code>
      <control_no>KORCIS-OLD-001</control_no>
      <call_no>古貴 594-장17ㅇ</call_no>
      <isbn></isbn>
      <doc_yn>Y</doc_yn>
      <org_link>https://www.nl.go.kr/NL/contents/original/001</org_link>
      <detail_link>/NL/contents/search.do?id=KORCIS-OLD-001</detail_link>
      <id>internal-2</id>
      <kdc_code_1s>590</kdc_code_1s>
      <kdc_name_1s>가정학</kdc_name_1s>
      <lic_yn>Y</lic_yn>
      <lic_text>협약공공도서관 무료</lic_text>
      <reg_date>19990101</reg_date>
    </item>
    <item>
      <title_info>약과 만드는 법</title_info>
      <control_no></control_no>
      <id>internal-3</id>
      <detail_link>http://example.test/already-absolute</detail_link>
    </item>
  </list>
</channel>"""


def test_parse_response_preserves_pagination_header() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    assert parsed.total_count == 1234
    assert parsed.page_num == 1
    assert parsed.page_size == 3
    assert len(parsed.results) == 3


def test_parse_response_maps_xml_tags_to_dataclass_attrs() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    first = parsed.results[0]
    assert first.external_id == "KMO201234567890"  # control_no preferred over id
    assert first.title == "토지"
    assert first.author == "박경리 지음"
    assert first.publisher == "마로니에북스"
    assert first.pub_year_raw == "2012"
    assert first.year == 2012
    assert first.period == "근대"
    assert first.type_name == "도서"
    assert first.call_number == "813.6-박52토"
    assert first.isbn == "9788984993727"
    assert first.kdc_code == "800"
    assert first.kdc_name == "문학"
    assert first.license_code == "L"
    assert first.license_text == "국립중앙도서관 무료 열람"
    assert first.has_original_text is False  # doc_yn=N


def test_parse_response_handles_legacy_publication_dates() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    second = parsed.results[1]
    assert second.external_id == "KORCIS-OLD-001"
    assert second.pub_year_raw == "순조 14년(1814년)"
    assert second.year == 1814
    assert second.period == "조선후기"
    assert second.has_original_text is True  # doc_yn=Y
    assert second.original_text_url == "https://www.nl.go.kr/NL/contents/original/001"
    assert second.type_name == "고문헌"


def test_parse_response_absolutises_relative_detail_link() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    assert parsed.results[0].detail_url == (
        f"{NLK_DEFAULT_BASE_URL}/NL/contents/search.do?id=KMO201234567890"
    )


def test_parse_response_preserves_already_absolute_detail_link() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    assert parsed.results[2].detail_url == "http://example.test/already-absolute"


def test_parse_response_falls_back_to_id_when_control_no_blank() -> None:
    """The 3rd sample item has an empty <control_no> but a non-empty <id>."""
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    third = parsed.results[2]
    assert third.external_id == "internal-3"
    assert third.title == "약과 만드는 법"


def test_parse_response_skips_items_missing_both_id_and_title() -> None:
    xml = """<?xml version="1.0"?>
    <channel>
      <total>2</total><pageNum>1</pageNum><pageSize>10</pageSize>
      <list>
        <item><call_no>813.6</call_no></item>
        <item><control_no>KEEP</control_no><title_info>샘플</title_info></item>
      </list>
    </channel>"""
    parsed = _parse_response(xml)
    assert [r.external_id for r in parsed.results] == ["KEEP"]


def test_parse_response_tolerates_malformed_header_counts() -> None:
    xml = """<?xml version="1.0"?>
    <channel>
      <total>not-a-number</total><pageNum></pageNum><pageSize>many</pageSize>
      <list></list>
    </channel>"""
    parsed = _parse_response(xml)
    assert parsed.total_count == 0
    assert parsed.page_num == 1  # default
    assert parsed.page_size == 0
    assert parsed.results == ()


def test_parse_response_tolerates_partial_schema_change() -> None:
    """If upstream drops non-essential elements we keep going."""
    xml = """<?xml version="1.0"?>
    <channel>
      <total>1</total><pageNum>1</pageNum><pageSize>1</pageSize>
      <list>
        <item>
          <control_no>UCI_X</control_no>
          <title_info>테스트</title_info>
        </item>
      </list>
    </channel>"""
    parsed = _parse_response(xml)
    assert parsed.results[0].external_id == "UCI_X"
    assert parsed.results[0].author == ""
    assert parsed.results[0].publisher == ""
    assert parsed.results[0].year is None
    assert parsed.results[0].period == ""


def test_parse_response_tolerates_items_outside_list_wrapper() -> None:
    """Some queries return <item> directly under <channel> with no <list>."""
    xml = """<?xml version="1.0"?>
    <channel>
      <total>1</total><pageNum>1</pageNum><pageSize>1</pageSize>
      <item>
        <control_no>NO_LIST</control_no>
        <title_info>샘플</title_info>
      </item>
    </channel>"""
    parsed = _parse_response(xml)
    assert [r.external_id for r in parsed.results] == ["NO_LIST"]


def test_parse_response_raises_on_upstream_error_envelope() -> None:
    """`<error>` root → re-raise as NlkAPIError with error_code preserved."""
    xml = (
        "<?xml version='1.0'?>"
        "<error><error_code>011</error_code>"
        "<msg>INVALID KEY:인증키값이 유효하지 않습니다.</msg></error>"
    )
    with pytest.raises(NlkAPIError) as excinfo:
        _parse_response(xml)
    assert excinfo.value.error_code == "011"
    assert "INVALID KEY" in str(excinfo.value)


def test_parse_response_raises_on_unknown_error_envelope_without_code() -> None:
    xml = "<?xml version='1.0'?><error><msg>boom</msg></error>"
    with pytest.raises(NlkAPIError) as excinfo:
        _parse_response(xml)
    assert excinfo.value.error_code is None
    assert "boom" in str(excinfo.value)


def test_parse_response_raises_on_non_xml() -> None:
    with pytest.raises(NlkAPIError, match="non-XML"):
        _parse_response("<<<not xml>>>")


def test_parse_response_raises_on_unexpected_root() -> None:
    with pytest.raises(NlkAPIError, match="unexpected root"):
        _parse_response("<root><foo/></root>")


# ---------------------------------------------------------------------------
# NlkSearchClient — request shape & error handling
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    return resp


def test_client_requires_api_key_at_construction() -> None:
    with pytest.raises(ValueError, match="NLK_API_KEY is required"):
        NlkSearchClient(api_key="")


def test_client_hits_search_endpoint_with_default_base_url() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        url = mock_get.call_args.args[0]
        assert url == f"{NLK_DEFAULT_BASE_URL}/NL/search/openApi/search.do"


def test_client_strips_trailing_slash_on_base_url() -> None:
    client = NlkSearchClient(api_key="testkey", base_url="https://example.test/portal/")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        url = mock_get.call_args.args[0]
        assert url == "https://example.test/portal/NL/search/openApi/search.do"


def test_client_passes_required_params() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        params = mock_get.call_args.kwargs["params"]
        assert params["key"] == "testkey"
        assert params["kwd"] == "음식"
        assert params["srchTarget"] == "total"
        assert params["pageNum"] == 1
        assert params["pageSize"] == 10
        assert params["apiType"] == "xml"
        # default category is 고문헌 because this is a heritage adapter
        assert params["category"] == "고문헌"
        # systemType not provided → not sent
        assert "systemType" not in params


def test_client_passes_explicit_pagination_and_filters() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search(
            "약과",
            page_num=3,
            page_size=20,
            category="도서",
            system_type="온라인자료",
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["pageNum"] == 3
        assert params["pageSize"] == 20
        assert params["category"] == "도서"
        assert params["systemType"] == "온라인자료"


def test_client_skips_category_when_blank() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", category="")
        params = mock_get.call_args.kwargs["params"]
        assert "category" not in params


def test_client_caps_page_size_at_documented_max() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", page_size=99999)
        params = mock_get.call_args.kwargs["params"]
        assert params["pageSize"] == 500


def test_client_normalises_negative_page_num() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", page_num=0)
        params = mock_get.call_args.kwargs["params"]
        assert params["pageNum"] == 1


def test_client_rejects_empty_query() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="query is required"):
            client.search("")
        mock_get.assert_not_called()


def test_client_raises_api_error_on_404_with_endpoint_hint() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(404, "")
        with pytest.raises(NlkAPIError, match="endpoint may have moved"):
            client.search("음식")


def test_client_raises_api_error_on_429() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(429, "")
        with pytest.raises(NlkAPIError, match="rate limit"):
            client.search("음식")


def test_client_raises_api_error_on_500() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(503, "service unavailable")
        with pytest.raises(NlkAPIError, match="503"):
            client.search("음식")


def test_client_raises_api_error_on_network_failure() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("DNS failure")):
        with pytest.raises(NlkAPIError, match="request failed"):
            client.search("음식")


def test_client_raises_api_error_on_non_xml_body() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, "not xml at all")
        with pytest.raises(NlkAPIError, match="non-XML"):
            client.search("음식")


def test_client_surfaces_upstream_invalid_key_error() -> None:
    """The endpoint returns 200 with an <error> envelope on bad keys."""
    client = NlkSearchClient(api_key="badkey")
    err_xml = (
        "<?xml version='1.0'?>"
        "<error><error_code>011</error_code>"
        "<msg>INVALID KEY:인증키값이 유효하지 않습니다.</msg></error>"
    )
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, err_xml)
        with pytest.raises(NlkAPIError) as excinfo:
            client.search("음식")
        assert excinfo.value.error_code == "011"


def test_client_returns_parsed_response_on_success() -> None:
    client = NlkSearchClient(api_key="testkey")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        response = client.search("음식")
        assert response.total_count == 1234
        assert len(response.results) == 3
        assert isinstance(response.results[0], NlkSearchResult)
        assert response.results[0].year == 2012
