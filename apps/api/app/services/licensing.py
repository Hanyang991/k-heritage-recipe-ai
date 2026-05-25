"""Per-institution license registry + attribution formatter (spec §3.1).

Spec §3.1 "라이선스 근거 (상업적 활용 적법성)" — all integrated public
archives ship under **공공누리 (KOGL) 제1유형**:

    출처 표시 조건 하에 상업적 이용·변형·재배포가 허용됩니다.
    레시피 생성 결과물에는 '출처: OO 고문헌 (장서각/국립민속박물관/문화데이터광장)'을 자동 삽입
    하여 라이선스 조건을 준수합니다.

This module is the **single source of truth** for that compliance
contract. Every surface that exposes heritage data to end users — the
public document detail endpoint, the recipe payload, the PDF / cert
export, the SNS caption — goes through :func:`get_license_notice` and
:func:`format_attribution` so the project meets the KOGL Type 1
"source-must-be-cited" obligation in exactly one consistent way.

Adding a new heritage source is two steps:

1. Add a :class:`LicenseNotice` entry to :data:`LICENSE_REGISTRY` keyed
   by the institution code already used in
   ``HeritageDoc.institution`` (matching the constants in
   ``app/services/heritage/<source>.py`` — ``JANGSEOGAK_INSTITUTION_CODE``
   etc.).
2. Verify the operator-confirmation note in the entry: KOGL types can
   change when an institution updates its terms, so each entry carries
   the date of last manual verification (spec §3.1 footnote: "서비스
   출시 전 각 기관의 이용약관 최종 확인 필수").

The fallback :data:`UNKNOWN_LICENSE` keeps the contract intact for
unexpected institution codes — better to show "KOGL-1, attribution
required, terms unverified" than to silently emit unattributed content.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LicenseNotice:
    """Structured per-institution license & attribution record.

    Surfaces:

    * ``code`` / ``name`` — short and long license labels for UI
      badges (e.g. "KOGL-1" / "공공누리 제1유형").
    * ``url`` — official license terms page. Linked from
      :class:`DocumentDetailOut` and the recipe response so users can
      audit the exact obligations.
    * ``institution_display_name`` — Korean display name for the
      institution that hosts the source. Used to format the spec-
      mandated "출처: OO 고문헌 (장서각/...)" attribution string.
    * ``attribution_template`` — printf-style template that consumes
      ``{title}``, ``{institution}``, ``{year}`` for the recipe / PDF
      attribution line. The default matches spec §3.1's exemplar.
    * ``permissions`` / ``obligations`` — machine-readable summary
      of what KOGL Type 1 grants and requires. The frontend
      surfaces these as bullet points on the document detail page so
      end users see the same compliance summary the legal team did.
    * ``terms_summary_ko`` — one-liner Korean summary suitable for
      a tooltip / footer next to the source line.
    * ``verified_on`` — ISO-8601 date the operator last manually
      checked the institution's terms page. Spec §3.1 footnote: KOGL
      types may change when institutions update their policy.
    """

    code: str
    name: str
    url: str
    institution_display_name: str
    attribution_template: str
    permissions: tuple[str, ...]
    obligations: tuple[str, ...]
    terms_summary_ko: str
    verified_on: str


# Standard KOGL Type 1 grants and obligations. All 5 currently-wired
# heritage sources use this profile per spec §3.1 (the 3 official sources
# plus the 2 follow-on integrations in PR #33 / #35 / #37). Keeping the
# tuples shared by reference (rather than re-typing the literals per
# entry) keeps the registry honest — bumping the policy summary in one
# place updates every source.
_KOGL_PERMISSIONS = (
    "commercial_use",
    "modification",
    "redistribution",
)
_KOGL_OBLIGATIONS = ("source_attribution",)
_KOGL_TERMS_SUMMARY_KO = (
    "공공누리 제1유형: 출처 표시 조건 하에 상업적 이용·변형·재배포가 허용됩니다."
)
_KOGL_URL = "https://www.kogl.or.kr/info/license.do#01-tab"


def _kogl_type_1(
    *,
    institution_display_name: str,
    verified_on: str,
    attribution_template: str = "출처: {title}{year_suffix} · {institution}",
) -> LicenseNotice:
    """Build the KOGL Type 1 :class:`LicenseNotice` for an institution.

    Factored out so each registry entry stays a one-liner — the
    license code / URL / permissions / obligations are identical
    across all KOGL Type 1 sources, only the institution-specific
    display name and the operator-verified-on date vary.
    """
    return LicenseNotice(
        code="KOGL-1",
        name="공공누리 제1유형 (출처표시)",
        url=_KOGL_URL,
        institution_display_name=institution_display_name,
        attribution_template=attribution_template,
        permissions=_KOGL_PERMISSIONS,
        obligations=_KOGL_OBLIGATIONS,
        terms_summary_ko=_KOGL_TERMS_SUMMARY_KO,
        verified_on=verified_on,
    )


# Keys here must match the ``HeritageDoc.institution`` values produced
# by the live adapters (the ``*_INSTITUTION_CODE`` constants in
# ``app/services/heritage/<source>.py``). The keys are also stored on
# ``Document.institution`` for seeded / indexed records.
LICENSE_REGISTRY: dict[str, LicenseNotice] = {
    "jangseogak": _kogl_type_1(
        # 한국학중앙연구원 장서각 디지털 아카이브 — spec §3.1 row 1.
        institution_display_name="한국학중앙연구원 장서각",
        verified_on="2026-05-25",
    ),
    "koreanstudies": _kogl_type_1(
        # 한국학자료포털 (kostma.aks.ac.kr) — operated by the same
        # institution as 장서각, listed separately in spec §3.1.
        institution_display_name="한국학중앙연구원 한국학자료포털",
        verified_on="2026-05-25",
    ),
    "nlk": _kogl_type_1(
        # 국립중앙도서관 Open API — service terms publish metadata
        # under KOGL Type 1; ``lic_yn`` facility-access flags on the
        # underlying records are unrelated.
        institution_display_name="국립중앙도서관",
        verified_on="2026-05-25",
    ),
    "gihohak": _kogl_type_1(
        # 기호유학 고문헌 통합정보시스템 (충남대) — operated under the
        # 국가DB사업 standard license per their data-portal terms.
        institution_display_name="충남대학교 기호유학 고문헌 통합정보시스템",
        verified_on="2026-05-25",
    ),
    "nfm": _kogl_type_1(
        # 국립민속박물관 (spec §3.1 row 2). Listed in spec's exemplar
        # attribution even though the live adapter is still on the
        # roadmap — the registry entry exists so the seeded / indexed
        # mock-NFM records still get a correct attribution string.
        institution_display_name="국립민속박물관",
        verified_on="2026-05-25",
    ),
    "culture": _kogl_type_1(
        # 문화데이터광장 (spec §3.1 row 3) — same status as ``nfm``:
        # roadmap adapter, registry entry already correct for seeded
        # and hybrid-indexed records.
        institution_display_name="문화데이터광장",
        verified_on="2026-05-25",
    ),
    "nihc": _kogl_type_1(
        # 국사편찬위 (todo.md §1.3.1 — final outstanding source). Entry
        # added pre-emptively so a future adapter PR is a one-line
        # change rather than three.
        institution_display_name="국사편찬위원회",
        verified_on="2026-05-25",
    ),
}


UNKNOWN_LICENSE = LicenseNotice(
    # Safety net for institution codes we haven't catalogued yet.
    # Still surfaces the KOGL-1 obligation so downstream consumers
    # never accidentally emit unattributed content — the only
    # difference from a real entry is the obviously-placeholder
    # display name + a ``verified_on`` of "" indicating the operator
    # has not signed off on this source.
    code="KOGL-1",
    name="공공누리 제1유형 (출처표시) — 기관 확인 필요",
    url=_KOGL_URL,
    institution_display_name="기타 공공기관",
    attribution_template="출처: {title}{year_suffix} · {institution}",
    permissions=_KOGL_PERMISSIONS,
    obligations=_KOGL_OBLIGATIONS,
    terms_summary_ko=_KOGL_TERMS_SUMMARY_KO,
    verified_on="",
)


def get_license_notice(institution: str) -> LicenseNotice:
    """Return the :class:`LicenseNotice` for an institution code.

    Falls back to :data:`UNKNOWN_LICENSE` for unknown codes (with the
    correct KOGL-1 obligations baked in) so a missing registry entry
    can never cause unattributed output downstream.
    """
    return LICENSE_REGISTRY.get(institution, UNKNOWN_LICENSE)


def format_attribution(
    institution: str,
    *,
    title: str,
    year: int | None = None,
) -> str:
    """Build the spec-§3.1 attribution string for a heritage record.

    Returns e.g. ``"출처: 음식디미방 (1670) · 한국학중앙연구원 장서각"`` —
    same shape as the existing ``_doc_source`` helper in
    ``app/services/llm/mock.py`` so the upgrade is byte-compatible
    for downstream consumers (PDF / SNS / recipe response).

    The institution name comes from the registry's
    ``institution_display_name`` rather than the raw code, so users
    see "한국학중앙연구원 장서각" rather than "jangseogak". Falls
    back to the raw title alone when neither title nor institution
    are usable — better to emit a minimal "출처: ..." line than to
    silently drop the attribution entirely.
    """
    notice = get_license_notice(institution)
    year_suffix = f" ({year})" if year else ""
    return notice.attribution_template.format(
        title=title or "공공누리 제1유형 데이터",
        year_suffix=year_suffix,
        institution=notice.institution_display_name,
    )


def known_institutions() -> list[str]:
    """List of catalogued institution codes (deterministic order)."""
    return list(LICENSE_REGISTRY.keys())


def resolve_institution_from_attribution(attribution: str) -> str | None:
    """Best-effort reverse lookup: attribution string → institution code.

    Recipes don't carry the source institution as a structured field —
    they only store the pre-formatted ``source_attribution`` line
    produced by the LLM (e.g. ``"출처: 음식디미방 (1670) · 한국학중앙
    연구원 장서각"``). For the structured ``license_notice`` field on
    :class:`~app.schemas.recipe.RecipeDetailOut` we need the
    institution code so the registry lookup works.

    We scan for each registered institution's ``institution_display_name``
    as a substring of ``attribution`` and return the first match. This
    is intentionally tolerant — partial matches ("장서각" inside
    "한국학중앙연구원 장서각") are still correctly attributed to the
    full-name entry because the registry's display names contain the
    short form. Returns ``None`` when no match is found so callers can
    fall back to :data:`UNKNOWN_LICENSE` without crashing.

    The fallback is rare in practice: live Gemini output is constrained
    by ``responseSchema`` (see ``app/services/llm/gemini.py``) to cite
    the exact attribution shape, and the mock adapter uses the same
    template. The catch-all is here for robustness against future
    prompt drift or hand-written legacy data.
    """
    if not attribution:
        return None
    for code, notice in LICENSE_REGISTRY.items():
        if notice.institution_display_name and notice.institution_display_name in attribution:
            return code
    # Common short aliases — display names already include the long
    # form ("한국학중앙연구원 장서각") so "장서각" alone also matches.
    # Add a couple of well-known short forms that aren't substrings of
    # the canonical display names but appear in the wild.
    short_aliases = {
        "장서각": "jangseogak",
        "한국학자료포털": "koreanstudies",
        "국립중앙도서관": "nlk",
        "기호유학": "gihohak",
        "국립민속박물관": "nfm",
        "문화데이터광장": "culture",
        "국사편찬위": "nihc",
    }
    for needle, code in short_aliases.items():
        if needle in attribution:
            return code
    return None
