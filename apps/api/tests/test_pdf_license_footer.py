"""Tests for the KOGL-1 license footer on exported PDFs (spec §3.1 / §13).

The recipe PDF and the heritage attestation certificate both need to
ship the spec-§3.1 attribution + the license URL so a shared / printed
copy stays compliance-correct out of the app.

reportlab compresses PDF page streams by default, so substring-grepping
the raw bytes for the URL doesn't work. Instead we monkeypatch
``Canvas.drawCentredString`` / ``Canvas.drawString`` to capture every
text-write the renderer issues, then assert the expected strings
appeared. This is robust to font/encoding details and surfaces the
exact strings the renderer wrote to the page.
"""

from __future__ import annotations

import pytest
from reportlab.pdfgen import canvas

from app.models.recipe import Recipe, RecipeStatus
from app.services.pdf import render_certificate_pdf, render_recipe_pdf


def _make_recipe(*, source_attribution: str) -> Recipe:
    """Build an in-memory Recipe (no DB) with sensible defaults."""
    return Recipe(
        id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        name="음식디미방 쑥라떼",
        description="장서각 음식디미방을 현대적으로 재해석한 레시피.",
        region="전라북도",
        era="조선후기",
        diet="비건",
        menu_type="디저트 음료",
        keyword="쑥라떼",
        difficulty="쉬움",
        time_minutes=15,
        servings=2,
        estimated_cost_krw=1200,
        estimated_price_krw=5500,
        steps=[{"title": "1단계", "description": "쑥을 손질한다."}],
        sns_caption="🌿 #쑥라떼",
        image_url="",
        source_attribution=source_attribution,
        is_recommended=True,
        status=RecipeStatus.APPROVED,
    )


@pytest.fixture()
def captured_text(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture every ``drawString`` / ``drawCentredString`` call.

    Returns the shared list — tests assert membership against it.
    Patching at the ``Canvas`` class level means we catch writes from
    every helper the renderer dispatches to (watermark, license footer,
    body copy) without coupling the test to the renderer's internal
    structure.
    """
    sink: list[str] = []
    real_draw = canvas.Canvas.drawString
    real_centered = canvas.Canvas.drawCentredString

    def fake_draw(self, x, y, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        sink.append(text)
        return real_draw(self, x, y, text, *args, **kwargs)

    def fake_centered(self, x, y, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        sink.append(text)
        return real_centered(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(canvas.Canvas, "drawString", fake_draw)
    monkeypatch.setattr(canvas.Canvas, "drawCentredString", fake_centered)
    return sink


def test_recipe_pdf_includes_kogl_attribution_and_license_url(
    captured_text: list[str],
) -> None:
    recipe = _make_recipe(source_attribution="출처: 음식디미방 (1670) · 한국학중앙연구원 장서각")
    pdf = render_recipe_pdf(recipe)
    assert pdf.startswith(b"%PDF")
    # The spec-mandated 출처 line is drawn verbatim on the page.
    assert any("출처: 음식디미방" in s for s in captured_text)
    # The license URL is drawn on the page so a printed / shared copy
    # carries the KOGL terms reference.
    assert any("kogl.or.kr" in s for s in captured_text)


def test_recipe_pdf_with_empty_attribution_still_emits_kogl_footer(
    captured_text: list[str],
) -> None:
    recipe = _make_recipe(source_attribution="")
    render_recipe_pdf(recipe)
    # No specific 출처 line, but the generic license URL must still be
    # on the page so any redistribution stays compliance-correct.
    assert any("kogl.or.kr" in s for s in captured_text)


def test_certificate_pdf_uses_license_name_and_url(
    captured_text: list[str],
) -> None:
    recipe = _make_recipe(source_attribution="출처: 음식디미방 (1670) · 한국학중앙연구원 장서각")
    pdf = render_certificate_pdf(recipe)
    assert pdf.startswith(b"%PDF")
    # The certificate's compliance footer cites the registry license
    # name AND the URL.
    assert any("공공누리 제1유형" in s for s in captured_text)
    assert any("kogl.or.kr" in s for s in captured_text)


def test_certificate_pdf_for_nlk_recipe_still_emits_kogl_url(
    captured_text: list[str],
) -> None:
    recipe = _make_recipe(source_attribution="출처: 조선요리법 (1939) · 국립중앙도서관")
    render_certificate_pdf(recipe)
    assert any("kogl.or.kr" in s for s in captured_text)


def test_recipe_pdf_renders_without_crashing_when_attribution_empty() -> None:
    """Smoke test: helper handles edge cases without exceptions."""
    recipe = _make_recipe(source_attribution="")
    pdf = render_recipe_pdf(recipe)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500  # Non-empty document
