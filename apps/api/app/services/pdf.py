"""Simple PDF export (FR-05, FR-06).

Uses reportlab to build a single-page recipe PDF in-memory. Free plan adds a
watermark across the page.

License footer (spec §3.1 / §13): every page that ships heritage-derived
content carries a KOGL-1 attribution footer with the license URL so the
PDF stays compliance-correct even when shared / printed out of the app.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app.models.recipe import Recipe
from app.services.licensing import (
    get_license_notice,
    resolve_institution_from_attribution,
)


def _draw_license_footer(c: canvas.Canvas, recipe: Recipe, width: float) -> None:
    """Draw the spec-§3.1 KOGL-1 attribution footer on the current page.

    Two lines, bottom of page, small italic — same visual treatment used
    on the heritage attestation certificate so the look stays consistent
    across exports:

    * Line 1: ``recipe.source_attribution`` (verbatim — already in the
      spec-mandated "출처: OO 고문헌 (...)" shape).
    * Line 2: the license name + URL from the registry so a recipient
      auditing the PDF can verify the redistribution terms in one
      click.

    Falls back gracefully when ``source_attribution`` is empty (legacy
    rows from before the heritage adapter was wired) by emitting only
    the generic KOGL-1 disclaimer line.
    """
    institution = resolve_institution_from_attribution(recipe.source_attribution or "") or "unknown"
    notice = get_license_notice(institution)
    c.saveState()
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    bottom = 1.2 * cm
    if recipe.source_attribution:
        c.drawCentredString(width / 2, bottom + 0.45 * cm, recipe.source_attribution)
    license_line = f"{notice.name} · {notice.url}"
    c.drawCentredString(width / 2, bottom, license_line)
    c.restoreState()


def _draw_watermark(c: canvas.Canvas, text: str) -> None:
    c.saveState()
    c.setFillColorRGB(0.85, 0.85, 0.85)
    c.setFont("Helvetica-Bold", 60)
    c.translate(10 * cm, 14 * cm)
    c.rotate(30)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def render_recipe_pdf(recipe: Recipe, watermark: bool = False) -> bytes:
    """Render a single-page A4 PDF for a recipe and return the raw bytes."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    if watermark:
        _draw_watermark(c, "FREE PLAN")

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontSize = 22

    y = height - 2 * cm

    # Title
    title_para = Paragraph(recipe.name, title_style)
    title_para.wrapOn(c, width - 4 * cm, 3 * cm)
    title_para.drawOn(c, 2 * cm, y - 1.2 * cm)
    y -= 2.5 * cm

    # Meta
    c.setFont("Helvetica", 10)
    c.drawString(
        2 * cm,
        y,
        f"Region: {recipe.region}  |  Era: {recipe.era}  |  Diet: {recipe.diet}  |  "
        f"Difficulty: {recipe.difficulty}  |  Time: {recipe.time_minutes} min",
    )
    y -= 0.8 * cm

    # Source
    if recipe.source_attribution:
        c.setFillColorRGB(0.55, 0.46, 0.0)
        c.drawString(2 * cm, y, recipe.source_attribution)
        c.setFillColorRGB(0, 0, 0)
        y -= 0.8 * cm

    # Description
    c.setFont("Helvetica", 11)
    for line in _wrap(recipe.description, 90):
        c.drawString(2 * cm, y, line)
        y -= 0.5 * cm

    y -= 0.5 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Ingredients")
    y -= 0.6 * cm
    c.setFont("Helvetica", 10)
    for ri in recipe.ingredients:
        c.drawString(2.4 * cm, y, f"- {ri.ingredient.name}: {ri.amount}")
        y -= 0.5 * cm

    y -= 0.4 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Steps")
    y -= 0.6 * cm
    c.setFont("Helvetica", 10)
    for i, step in enumerate(recipe.steps or [], start=1):
        title = step.get("title", "") if isinstance(step, dict) else getattr(step, "title", "")
        desc = (
            step.get("description", "")
            if isinstance(step, dict)
            else getattr(step, "description", "")
        )
        c.drawString(2.4 * cm, y, f"{i}. {title}")
        y -= 0.5 * cm
        for line in _wrap(desc, 90):
            c.drawString(3 * cm, y, line)
            y -= 0.45 * cm
        y -= 0.2 * cm

    _draw_license_footer(c, recipe, width)

    c.showPage()
    c.save()
    return buf.getvalue()


def render_certificate_pdf(recipe: Recipe) -> bytes:
    """Heritage attestation certificate (Pro/B2B only)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setStrokeColorRGB(0.21, 0.19, 0.64)
    c.setLineWidth(3)
    c.rect(1.5 * cm, 1.5 * cm, width - 3 * cm, height - 3 * cm)

    c.setFillColorRGB(0.21, 0.19, 0.64)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 4 * cm, "Heritage Attestation Certificate")
    c.setFillColorRGB(0, 0, 0)

    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 7 * cm, recipe.name)

    c.setFont("Helvetica", 11)
    c.drawCentredString(
        width / 2,
        height - 9 * cm,
        f"Region: {recipe.region}  |  Era: {recipe.era}",
    )
    c.drawCentredString(
        width / 2, height - 9.7 * cm, recipe.source_attribution or "공공누리 제1유형"
    )

    # Pull the registry entry so the cert footer carries the full
    # license name + URL — gives the holder a one-click path to verify
    # KOGL-1 terms without having to look up the project docs.
    institution = resolve_institution_from_attribution(recipe.source_attribution or "") or "unknown"
    notice = get_license_notice(institution)

    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(
        width / 2,
        3.2 * cm,
        f"This certificate confirms the recipe was generated from sources licensed under {notice.name}.",
    )
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawCentredString(width / 2, 2.4 * cm, notice.url)

    c.showPage()
    c.save()
    return buf.getvalue()


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    current = ""
    for word in text.split():
        if len(current) + len(word) + 1 > width:
            out.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        out.append(current)
    return out
