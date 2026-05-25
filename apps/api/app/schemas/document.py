"""Heritage document schemas — list summary, search match and full detail.

Three response shapes exist on purpose:

* :class:`DocumentOut` — lightweight list / search row. Excludes the
  large ``original_text`` / ``modern_text`` columns so a paginated
  search response stays small over the wire.
* :class:`DocumentDetailOut` — the full payload returned by
  ``GET /v1/documents/{id}`` (spec §3.1 / §13). Adds the classical
  Korean ``original_text``, modern Korean ``modern_text`` translation,
  timestamps, and a structured :class:`LicenseNoticeOut` so the
  frontend can render the KOGL-1 attribution + license URL inline.
* :class:`DocumentMatch` — search-match wrapper that pairs a
  lightweight :class:`DocumentOut` with the keyword/semantic match
  score.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.licensing import (
    LicenseNotice,
    format_attribution,
    get_license_notice,
    resolve_institution_from_attribution,
)


class LicenseNoticeOut(BaseModel):
    """Structured KOGL-1 license metadata for the document detail page.

    Mirrors :class:`app.services.licensing.LicenseNotice` 1:1 so the
    frontend has access to the same fields the backend uses to render
    PDFs / recipes. ``attribution`` is the pre-formatted spec-§3.1
    string ("출처: OO 고문헌 (...)") so clients don't need to know how
    to assemble it themselves.
    """

    code: str = Field(..., description="License code, e.g. 'KOGL-1'.")
    name: str = Field(..., description="Localised license name shown in UI.")
    url: str = Field(..., description="Official license terms page.")
    institution_display_name: str = Field(
        ..., description="Korean display name for the hosting institution."
    )
    attribution: str = Field(
        ...,
        description=(
            "Pre-formatted attribution string per spec §3.1, e.g. "
            "'출처: 음식디미방 (1670) · 한국학중앙연구원 장서각'."
        ),
    )
    permissions: list[str] = Field(
        ...,
        description=(
            "Machine-readable grant list, e.g. ['commercial_use', "
            "'modification', 'redistribution']."
        ),
    )
    obligations: list[str] = Field(
        ...,
        description="Machine-readable obligation list, e.g. ['source_attribution'].",
    )
    terms_summary_ko: str = Field(..., description="One-liner Korean summary of the license terms.")
    verified_on: str = Field(
        ...,
        description=(
            "ISO-8601 date the operator last manually verified the "
            "institution's license terms (empty for unverified)."
        ),
    )


def _license_notice_payload(
    institution: str,
    *,
    title: str,
    year: int | None,
) -> LicenseNoticeOut:
    notice: LicenseNotice = get_license_notice(institution)
    return LicenseNoticeOut(
        code=notice.code,
        name=notice.name,
        url=notice.url,
        institution_display_name=notice.institution_display_name,
        attribution=format_attribution(institution, title=title, year=year),
        permissions=list(notice.permissions),
        obligations=list(notice.obligations),
        terms_summary_ko=notice.terms_summary_ko,
        verified_on=notice.verified_on,
    )


def license_notice_from_recipe_inputs(
    *,
    institution: str | None,
    attribution: str,
) -> LicenseNoticeOut | None:
    """Build :class:`LicenseNoticeOut` from a recipe's stored attribution.

    Used by the recipe routes to attach a structured KOGL-1 notice to
    every recipe response. Caller passes the institution code if it
    knows one (e.g. from a linked ``source_document``); otherwise the
    function falls back to scanning the ``attribution`` string for a
    known institution display name via
    :func:`resolve_institution_from_attribution`.

    Returns ``None`` only when neither input is usable — that signal
    lets the route emit ``license_notice: null`` rather than a fake
    notice when there's genuinely no source linked to the recipe (the
    spec only mandates attribution for heritage-derived content).
    """
    code = institution or resolve_institution_from_attribution(attribution)
    if not code:
        return None
    # Recipe attribution already contains the formatted source line, so
    # we don't try to re-format it from registry data — we want to
    # surface what the recipe was actually shipped with. The
    # ``attribution`` field on the notice is the canonical
    # registry-formatted version (useful for consistency checks).
    notice = get_license_notice(code)
    return LicenseNoticeOut(
        code=notice.code,
        name=notice.name,
        url=notice.url,
        institution_display_name=notice.institution_display_name,
        attribution=attribution or notice.institution_display_name,
        permissions=list(notice.permissions),
        obligations=list(notice.obligations),
        terms_summary_ko=notice.terms_summary_ko,
        verified_on=notice.verified_on,
    )


class DocumentOut(BaseModel):
    """Lightweight document row for search results."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    institution: str
    region: str
    period: str
    category: str
    year: int | None
    summary: str
    license: str


class DocumentDetailOut(BaseModel):
    """Full document payload — spec §3.1 / §13 detail endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    institution: str
    region: str
    period: str
    category: str
    year: int | None
    summary: str
    original_text: str = Field(
        default="",
        description=(
            "Classical Korean / Hanja source text as ingested from the "
            "heritage archive. May be empty when the source API only "
            "exposes metadata + summary (e.g. NLK search rows)."
        ),
    )
    modern_text: str = Field(
        default="",
        description=(
            "Modern Korean translation of ``original_text`` (spec §6.1 "
            "Gemini classical-→-modern pipeline). May be empty until the "
            "translation job has run for this row."
        ),
    )
    license: str = Field(
        default="KOGL-1",
        description="Short license code — keep for backward compat with DocumentOut.",
    )
    license_notice: LicenseNoticeOut = Field(
        ...,
        description=(
            "Structured KOGL-1 license metadata (institution display "
            "name, license URL, pre-formatted attribution string, "
            "permissions, obligations). Generated server-side from the "
            "shared license registry so every surface emits the same "
            "compliance-correct fields."
        ),
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, obj: object) -> DocumentDetailOut:
        """Build the response from a :class:`~app.models.document.Document`.

        Centralised here so the route handler stays a one-liner — the
        license notice synthesis needs to read ``institution`` + ``title``
        + ``year`` off the ORM row, which would otherwise leak that
        concern into the router.
        """
        # Pulled via getattr so this same constructor still works against
        # ad-hoc test doubles that aren't full ORM rows.
        institution = getattr(obj, "institution", "")
        title = getattr(obj, "title", "")
        year = getattr(obj, "year", None)
        return cls(
            id=obj.id,
            title=title,
            institution=institution,
            region=getattr(obj, "region", ""),
            period=getattr(obj, "period", ""),
            category=getattr(obj, "category", ""),
            year=year,
            summary=getattr(obj, "summary", ""),
            original_text=getattr(obj, "original_text", "") or "",
            modern_text=getattr(obj, "modern_text", "") or "",
            license=getattr(obj, "license", "KOGL-1") or "KOGL-1",
            license_notice=_license_notice_payload(institution, title=title, year=year),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class DocumentMatch(BaseModel):
    """A document returned by vector/keyword search, paired with a match score."""

    document: DocumentOut
    match_score: float
