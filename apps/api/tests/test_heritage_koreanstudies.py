"""Unit tests for :mod:`app.services.heritage.koreanstudies`.

Network is mocked everywhere — the live adapter is exercised by
``test_heritage_live_koreanstudies_adapter.py``. The XML samples below
mirror what ``https://kostma.aks.ac.kr/OpenAPI/request.aspx`` returns
in production (captured via curl against the live endpoint).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.heritage.koreanstudies import (
    KOREANSTUDIES_DEFAULT_BASE_URL,
    KoreanstudiesAPIError,
    KoreanstudiesSearchClient,
    KoreanstudiesSearchResult,
    _parse_response,
    derive_year_and_period,
)

# ---------------------------------------------------------------------------
# derive_year_and_period — pure helper (shared logic with 장서각)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1670", (1670, "조선후기")),
        ("1903(光武 7)", (1903, "근대")),
        ("1903(光武 7) ", (1903, "근대")),
        ("1500", (1500, "조선전기")),
        ("1593", (1593, "조선후기")),
        ("1897", (1897, "근대")),
        ("", (None, "")),
        ("연대미상", (None, "")),
        ("고종 40년(1903년) 사찬발기", (1903, "근대")),
        # kostma-specific: 정보원표기 sometimes has 갑술/을사 era names with
        # the CE year alongside.
        ("1874(고종 11)", (1874, "조선후기")),
    ],
)
def test_derive_year_and_period(raw: str, expected: tuple[int | None, str]) -> None:
    assert derive_year_and_period(raw) == expected


# ---------------------------------------------------------------------------
# _parse_response — XML envelope → typed objects
# ---------------------------------------------------------------------------


_LIVE_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ksm>
  <info>
    <request><![CDATA[/OpenAPI/request.aspx?query=%EC%9D%8C%EC%8B%9D&detail=1&ipp=3]]></request>
    <total>5</total>
    <page>1</page>
    <ipp>3</ipp>
  </info>
  <items>
    <item>
      <uci>G002+AKS+KSM-XG.0000.1100-20101008.B009a_012_00343_XXX</uci>
      <title>음식 발기(飮食件記)</title>
      <기본정보 UCI="G002+AKS+KSM-XG.0000.1100-20101008.B009a_012_00343_XXX-DES.BSC">
        <분류>
          <분류명 종류="형식분류">고문서-치부기록류-발기</분류명>
          <분류명 종류="내용분류">국왕/왕실-의례-발기</분류명>
        </분류>
        <자료명>음식 발기(飮食件記)</자료명>
        <작성지역 현재주소="서울특별시" 고지명ID="DYD_02_03_0218">한성</작성지역>
        <작성시기 정보원표기="1874(고종 11)" 월일="" 월일음양구분="" 생산기간="" />
        <비고>출판정보 : 『고문서집성 12 -장서각편-』(한국정신문화연구원, 1994)</비고>
      </기본정보>
      <url>http://kostma.aks.ac.kr/inspection/insDirView.aspx?dataUCI=G002+AKS+KSM-XG.0000.1100-20101008.B009a_012_00343_XXX</url>
    </item>
    <item>
      <uci>G002+AKS+KSM-XG.0000.1111-20101008.B009a_013_00247_XXX</uci>
      <title>갑술년 음식 발기(飮食件記)</title>
      <기본정보 UCI="bsc">
        <분류>
          <분류명 종류="형식분류">고문서-치부기록류-발기</분류명>
          <분류명 종류="내용분류">국왕/왕실-의례-발기</분류명>
        </분류>
        <자료명>갑술년 음식 발기(飮食件記)</자료명>
        <작성지역 현재주소="" />
        <작성시기 정보원표기="" />
      </기본정보>
      <url>http://kostma.aks.ac.kr/inspection/insDirView.aspx?dataUCI=G002+AKS+KSM-XG.0000.1111-20101008.B009a_013_00247_XXX</url>
    </item>
    <item>
      <uci>G002+AKS+KSM-XG.0000.0000-20101008.B059a_085_00477_XXX</uci>
      <title>신연 하인 음식 발긔</title>
      <url>http://kostma.aks.ac.kr/inspection/insDirView.aspx?dataUCI=G002+AKS+KSM-XG.0000.0000-20101008.B059a_085_00477_XXX</url>
    </item>
  </items>
</ksm>"""


def test_parse_response_preserves_pagination_header() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    assert parsed.total_count == 5
    assert parsed.page == 1
    assert parsed.ipp == 3
    assert len(parsed.results) == 3


def test_parse_response_maps_korean_xml_tags_to_dataclass_attrs() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    first = parsed.results[0]
    assert first.external_id.startswith("G002+AKS+KSM-XG.0000.1100")
    assert first.title == "음식 발기(飮食件記)"
    assert first.detail_url.startswith("http://kostma.aks.ac.kr/inspection/")
    assert first.type_category == "고문서-치부기록류-발기"
    assert first.content_category == "국왕/왕실-의례-발기"
    assert first.region_modern == "서울특별시"
    assert first.region_historical == "한성"
    assert first.composition_period_raw == "1874(고종 11)"
    assert first.year == 1874
    assert first.period == "조선후기"
    assert "출판정보" in first.summary


def test_parse_response_handles_missing_basic_info() -> None:
    """Third item has detail=0 shape (no 기본정보) — should still parse."""
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    third = parsed.results[2]
    assert third.external_id.endswith("00477_XXX")
    assert third.title == "신연 하인 음식 발긔"
    assert third.type_category == ""
    assert third.content_category == ""
    assert third.region_modern == ""
    assert third.year is None
    assert third.period == ""
    assert third.summary == ""


def test_parse_response_handles_empty_composition_period() -> None:
    parsed = _parse_response(_LIVE_SAMPLE_XML)
    second = parsed.results[1]
    assert second.composition_period_raw == ""
    assert second.year is None
    assert second.period == ""


def test_parse_response_skips_items_with_no_uci_and_no_title() -> None:
    xml = """<?xml version="1.0"?>
    <ksm>
      <info><total>2</total><page>1</page><ipp>10</ipp></info>
      <items>
        <item><url>http://kostma.example/x</url></item>
        <item><uci>KEEP</uci><title>샘플</title></item>
      </items>
    </ksm>"""
    parsed = _parse_response(xml)
    assert [r.external_id for r in parsed.results] == ["KEEP"]


def test_parse_response_tolerates_malformed_header_counts() -> None:
    xml = """<?xml version="1.0"?>
    <ksm>
      <info><total>not-a-number</total><page></page><ipp>many</ipp></info>
      <items></items>
    </ksm>"""
    parsed = _parse_response(xml)
    assert parsed.total_count == 0
    assert parsed.page == 1  # default fallback
    assert parsed.ipp == 0
    assert parsed.results == ()


def test_parse_response_tolerates_partial_schema_change() -> None:
    """If upstream drops a non-essential element we keep going."""
    xml = """<?xml version="1.0"?>
    <ksm>
      <info><total>1</total><page>1</page><ipp>1</ipp></info>
      <items>
        <item>
          <uci>UCI_X</uci>
          <title>테스트</title>
          <기본정보>
            <자료명>테스트</자료명>
          </기본정보>
        </item>
      </items>
    </ksm>"""
    parsed = _parse_response(xml)
    assert parsed.results[0].external_id == "UCI_X"
    assert parsed.results[0].type_category == ""
    assert parsed.results[0].region_modern == ""
    assert parsed.results[0].year is None


def test_parse_response_falls_back_to_basic_info_title_when_top_level_blank() -> None:
    xml = """<?xml version="1.0"?>
    <ksm>
      <info><total>1</total><page>1</page><ipp>1</ipp></info>
      <items>
        <item>
          <uci>UCI_Y</uci>
          <title></title>
          <기본정보>
            <자료명>기본정보에서 가져온 제목</자료명>
          </기본정보>
        </item>
      </items>
    </ksm>"""
    parsed = _parse_response(xml)
    assert parsed.results[0].title == "기본정보에서 가져온 제목"


def test_parse_response_concatenates_안내정보_into_summary_when_detail_2() -> None:
    xml = """<?xml version="1.0"?>
    <ksm>
      <info><total>1</total><page>1</page><ipp>1</ipp></info>
      <items>
        <item>
          <uci>UCI_Z</uci>
          <title>샘플</title>
          <기본정보>
            <비고>비고 텍스트</비고>
          </기본정보>
          <안내정보>
            <안내정보자료 UCI="" 안내정보구분="자료">
              <표제어>표제어 텍스트</표제어>
              <내용>
                <문단>문단 첫째 줄</문단>
                <문단>문단 둘째 줄</문단>
              </내용>
            </안내정보자료>
          </안내정보>
        </item>
      </items>
    </ksm>"""
    parsed = _parse_response(xml)
    summary = parsed.results[0].summary
    assert "비고 텍스트" in summary
    assert "표제어 텍스트" in summary
    assert "문단 첫째 줄" in summary
    assert "문단 둘째 줄" in summary


def test_parse_response_raises_on_non_xml() -> None:
    with pytest.raises(KoreanstudiesAPIError, match="non-XML"):
        _parse_response("<<<not xml>>>")


def test_parse_response_raises_on_unexpected_root() -> None:
    with pytest.raises(KoreanstudiesAPIError, match="unexpected root"):
        _parse_response("<root><foo/></root>")


# ---------------------------------------------------------------------------
# KoreanstudiesSearchClient — request shape & error handling
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    return resp


def test_client_hits_request_endpoint_with_default_base_url() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        url = mock_get.call_args.args[0]
        assert url == f"{KOREANSTUDIES_DEFAULT_BASE_URL}/OpenAPI/request.aspx"


def test_client_strips_trailing_slash_on_base_url() -> None:
    client = KoreanstudiesSearchClient(base_url="https://example.test/portal/")
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        url = mock_get.call_args.args[0]
        assert url == "https://example.test/portal/OpenAPI/request.aspx"


def test_client_passes_default_params() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식")
        params = mock_get.call_args.kwargs["params"]
        assert params["query"] == "음식"
        assert params["page"] == 1
        assert params["ipp"] == 20  # _DEFAULT_IPP
        assert params["detail"] == 1


def test_client_passes_explicit_pagination_and_detail() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("약과", ipp=5, page=3, detail=2)
        params = mock_get.call_args.kwargs["params"]
        assert params["ipp"] == 5
        assert params["page"] == 3
        assert params["detail"] == 2


def test_client_caps_ipp_at_max() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        client.search("음식", ipp=9999)
        params = mock_get.call_args.kwargs["params"]
        assert params["ipp"] == 100


def test_client_rejects_empty_query() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="query is required"):
            client.search("")
        mock_get.assert_not_called()


def test_client_rejects_invalid_detail() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        with pytest.raises(ValueError, match="detail must be"):
            client.search("음식", detail=5)
        mock_get.assert_not_called()


def test_client_raises_api_error_on_404_with_endpoint_hint() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(404, "")
        with pytest.raises(KoreanstudiesAPIError, match="endpoint may have moved"):
            client.search("음식")


def test_client_raises_api_error_on_429() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(429, "")
        with pytest.raises(KoreanstudiesAPIError, match="rate limit"):
            client.search("음식")


def test_client_raises_api_error_on_500() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(503, "service unavailable")
        with pytest.raises(KoreanstudiesAPIError, match="503"):
            client.search("음식")


def test_client_raises_api_error_on_network_failure() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("DNS failure")):
        with pytest.raises(KoreanstudiesAPIError, match="request failed"):
            client.search("음식")


def test_client_raises_api_error_on_non_xml_body() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, "not xml at all")
        with pytest.raises(KoreanstudiesAPIError, match="non-XML"):
            client.search("음식")


def test_client_returns_parsed_response_on_success() -> None:
    client = KoreanstudiesSearchClient()
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = _mock_response(200, _LIVE_SAMPLE_XML)
        response = client.search("음식")
        assert response.total_count == 5
        assert len(response.results) == 3
        assert isinstance(response.results[0], KoreanstudiesSearchResult)
        assert response.results[0].year == 1874
