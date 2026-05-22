"""Simple PDF export (FR-05, FR-06).

Uses reportlab to build a single-page recipe PDF in-memory. Free plan adds a
watermark across the page.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app.models.recipe import Recipe


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
    c.drawCentredString(width / 2, height - 9.7 * cm, recipe.source_attribution or "공공누리 제1유형")

    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(
        width / 2,
        2.5 * cm,
        "This certificate confirms the recipe was generated from sources licensed under KOGL Type 1.",
    )

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
