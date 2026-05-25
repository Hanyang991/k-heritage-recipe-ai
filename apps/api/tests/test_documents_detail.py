"""Integration tests for ``GET /v1/documents/{id}`` (spec §3.1 / §13).

Covers the new detail endpoint contract:

* Returns ``original_text`` + ``modern_text`` (the list endpoint
  intentionally omits these to keep search responses small).
* Returns a structured ``license_notice`` with the spec-§3.1
  KOGL-1 metadata + the pre-formatted "출처: ..." attribution
  string.
* 404 path still emits the structured error envelope used elsewhere
  in the API.
* Search endpoint (lightweight) and detail endpoint (full) share the
  same row but differ in payload shape, which guards against an
  accidental regression where the search route starts streaming
  full text bodies.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.document import Document


@pytest.fixture()
def jangseogak_document(db_session: Session) -> Document:
    """Persist a single 장서각 Document with original + modern text."""
    doc = Document(
        id="11111111-2222-3333-4444-555555555555",
        title="음식디미방",
        institution="jangseogak",
        region="경상도",
        period="조선후기",
        category="요리서",
        year=1670,
        summary="현존하는 한글로 쓰인 가장 오래된 조리서.",
        original_text="국슈는 그 만드는 법이 매우 까다로워 ...",
        modern_text="국수는 만드는 법이 매우 까다로워 ...",
        license="KOGL-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db_session.add(doc)
    db_session.commit()
    return doc


def test_detail_returns_original_and_modern_text(
    client: TestClient, jangseogak_document: Document
) -> None:
    """Detail endpoint must expose both ``original_text`` and ``modern_text``."""
    response = client.get(f"/v1/documents/{jangseogak_document.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == jangseogak_document.id
    assert body["title"] == "음식디미방"
    assert body["original_text"].startswith("국슈는 그 만드는 법")
    assert body["modern_text"].startswith("국수는 만드는 법")
    # Metadata still present.
    assert body["region"] == "경상도"
    assert body["period"] == "조선후기"
    assert body["category"] == "요리서"
    assert body["year"] == 1670


def test_detail_returns_structured_license_notice(
    client: TestClient, jangseogak_document: Document
) -> None:
    """Spec §3.1 license_notice surfaces KOGL-1 + the canonical attribution."""
    body = client.get(f"/v1/documents/{jangseogak_document.id}").json()
    notice = body["license_notice"]
    assert notice["code"] == "KOGL-1"
    assert notice["name"].startswith("공공누리 제1유형")
    assert notice["url"].startswith("https://www.kogl.or.kr/")
    assert notice["institution_display_name"] == "한국학중앙연구원 장서각"
    # Pre-formatted attribution must match spec §3.1 exemplar.
    assert notice["attribution"] == "출처: 음식디미방 (1670) · 한국학중앙연구원 장서각"
    # Machine-readable permissions / obligations.
    assert "commercial_use" in notice["permissions"]
    assert "modification" in notice["permissions"]
    assert "redistribution" in notice["permissions"]
    assert "source_attribution" in notice["obligations"]
    assert notice["verified_on"]  # non-empty — operator signed off


def test_detail_includes_timestamps(client: TestClient, jangseogak_document: Document) -> None:
    body = client.get(f"/v1/documents/{jangseogak_document.id}").json()
    assert "created_at" in body
    assert "updated_at" in body
    # Both ISO 8601 strings.
    assert body["created_at"].startswith("2026-01-01")
    assert body["updated_at"].startswith("2026-01-02")


def test_detail_404_uses_structured_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/documents/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    detail = body.get("detail") or body
    assert detail["error"] == "DOCUMENT_NOT_FOUND"
    assert detail["status"] == 404


def test_search_endpoint_still_returns_lightweight_payload(
    client: TestClient, jangseogak_document: Document
) -> None:
    """Search must NOT include full bodies — they belong on the detail page."""
    response = client.get("/v1/documents", params={"q": "음식디미방"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "음식디미방"
    # No original_text / modern_text / license_notice on the
    # lightweight schema — search responses should stay small.
    assert "original_text" not in row
    assert "modern_text" not in row
    assert "license_notice" not in row


def test_detail_for_nlk_document_uses_nlk_attribution(
    client: TestClient, db_session: Session
) -> None:
    """Detail endpoint picks the right institution from the registry."""
    doc = Document(
        id="22222222-3333-4444-5555-666666666666",
        title="조선요리법",
        institution="nlk",
        region="",
        period="근대",
        category="요리서",
        year=1939,
        summary="국립중앙도서관 소장 근대 요리서.",
        original_text="",
        modern_text="",
        license="KOGL-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db_session.add(doc)
    db_session.commit()

    body = client.get(f"/v1/documents/{doc.id}").json()
    assert body["license_notice"]["institution_display_name"] == "국립중앙도서관"
    assert body["license_notice"]["attribution"] == "출처: 조선요리법 (1939) · 국립중앙도서관"


def test_detail_for_unknown_institution_still_returns_kogl1_notice(
    client: TestClient, db_session: Session
) -> None:
    """A row with an un-catalogued institution code still gets KOGL-1 obligations."""
    doc = Document(
        id="33333333-4444-5555-6666-777777777777",
        title="미상문헌",
        institution="bogus-code",  # not in the registry
        region="",
        period="",
        category="",
        year=None,
        summary="",
        original_text="",
        modern_text="",
        license="KOGL-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db_session.add(doc)
    db_session.commit()

    notice = client.get(f"/v1/documents/{doc.id}").json()["license_notice"]
    assert notice["code"] == "KOGL-1"
    # Fallback display name signals to the operator the source needs cataloguing.
    assert "기타 공공기관" in notice["institution_display_name"]
    # No verified_on date because the operator hasn't signed off.
    assert notice["verified_on"] == ""
    assert "source_attribution" in notice["obligations"]
