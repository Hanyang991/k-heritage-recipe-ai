"""Unit tests for the canonical license registry (spec §3.1 / §13).

These tests guarantee the project-wide KOGL-1 compliance contract:

* Every catalogued institution returns a properly-shaped
  :class:`~app.services.licensing.LicenseNotice` with the correct
  KOGL-1 grants / obligations / URL.
* The fallback :data:`~app.services.licensing.UNKNOWN_LICENSE` is
  served for unknown institution codes so we never accidentally emit
  un-attributed content.
* :func:`format_attribution` produces the spec-§3.1 exemplar shape.
* :func:`resolve_institution_from_attribution` correctly reverses
  the attribution string back to an institution code (long form,
  short alias, partial match).

Future heritage sources are added by extending ``LICENSE_REGISTRY``;
adding a new entry is exercised here only as a smoke test against
the existing entries — the parametrised case keeps the cost of
adding a new source ~zero.
"""

from __future__ import annotations

import pytest

from app.services.licensing import (
    LICENSE_REGISTRY,
    UNKNOWN_LICENSE,
    LicenseNotice,
    format_attribution,
    get_license_notice,
    known_institutions,
    resolve_institution_from_attribution,
)


def test_registry_includes_every_live_heritage_source() -> None:
    """Every adapter wired into ``HERITAGE_MULTI_SOURCES`` must be catalogued.

    Locks the registry against drift: when a new adapter ships the
    operator must add the entry here, not silently emit
    ``UNKNOWN_LICENSE`` in production.
    """
    expected = {"jangseogak", "koreanstudies", "nlk", "gihohak", "nfm", "culture", "nihc"}
    assert expected.issubset(set(known_institutions()))


@pytest.mark.parametrize("institution", sorted(LICENSE_REGISTRY.keys()))
def test_every_entry_is_kogl_type_1_and_compliance_correct(institution: str) -> None:
    notice = get_license_notice(institution)
    assert notice.code == "KOGL-1"
    assert "공공누리" in notice.name
    assert notice.url.startswith("https://www.kogl.or.kr/")
    # All KOGL Type 1 sources grant the same three permissions and
    # require source attribution.
    assert "commercial_use" in notice.permissions
    assert "modification" in notice.permissions
    assert "redistribution" in notice.permissions
    assert "source_attribution" in notice.obligations
    # Every catalogued entry must have an operator-verified-on date
    # (the fallback gets "" — verified_on is empty only for that
    # safety net).
    assert notice.verified_on, f"institution {institution!r} missing verified_on"


def test_get_license_notice_falls_back_to_unknown() -> None:
    notice = get_license_notice("not-a-real-source")
    assert notice is UNKNOWN_LICENSE
    # The fallback must still carry KOGL-1 obligations — silent
    # missing-attribution is the bug we're guarding against.
    assert notice.obligations == ("source_attribution",)
    assert notice.permissions == ("commercial_use", "modification", "redistribution")
    assert notice.verified_on == ""  # the sentinel that flags "unverified"


def test_format_attribution_matches_spec_exemplar() -> None:
    # Spec §3.1 exemplar: 출처: OO 고문헌 (장서각/...)
    out = format_attribution("jangseogak", title="음식디미방", year=1670)
    assert out == "출처: 음식디미방 (1670) · 한국학중앙연구원 장서각"


def test_format_attribution_omits_year_when_missing() -> None:
    out = format_attribution("jangseogak", title="음식디미방", year=None)
    assert out == "출처: 음식디미방 · 한국학중앙연구원 장서각"


def test_format_attribution_for_unknown_institution_still_emits_source_line() -> None:
    # Even a misconfigured institution code must produce an attribution
    # string — the spec obligation is non-negotiable.
    out = format_attribution("bogus-code", title="조선요리법", year=1939)
    assert out.startswith("출처: 조선요리법 (1939)")
    assert "기타 공공기관" in out


def test_format_attribution_with_empty_title_falls_back_to_kogl_label() -> None:
    out = format_attribution("nlk", title="", year=None)
    # When title is missing we still ship a source line — the placeholder
    # is intentionally obvious so operators notice the upstream record
    # is malformed.
    assert "공공누리 제1유형 데이터" in out


def test_resolve_institution_from_attribution_long_form() -> None:
    # The canonical attribution shape uses the full institution display
    # name.
    code = resolve_institution_from_attribution("출처: 음식디미방 (1670) · 한국학중앙연구원 장서각")
    assert code == "jangseogak"


def test_resolve_institution_from_attribution_short_alias() -> None:
    # Legacy or hand-written attributions sometimes use only the short
    # form — the reverse-lookup must still recover the institution.
    assert resolve_institution_from_attribution("출처: 어쩌고 · 장서각") == "jangseogak"
    assert resolve_institution_from_attribution("출처: 책 · 국립중앙도서관") == "nlk"
    assert resolve_institution_from_attribution("출처: 책 · 기호유학") == "gihohak"


def test_resolve_institution_from_attribution_returns_none_for_unknown() -> None:
    assert resolve_institution_from_attribution("") is None
    assert resolve_institution_from_attribution("출처: 미상 · 어디지") is None


def test_license_notice_is_immutable_dataclass() -> None:
    # We rely on the registry entries being safe to share by reference
    # across requests (no per-request mutation). ``@dataclass(frozen=True)``
    # raises ``FrozenInstanceError`` on any attribute write.
    from dataclasses import FrozenInstanceError

    notice = get_license_notice("jangseogak")
    with pytest.raises(FrozenInstanceError):
        notice.code = "OTHER"  # type: ignore[misc]


def test_license_notice_is_the_expected_dataclass_type() -> None:
    # Sanity check — the schema layer imports LicenseNotice and relies
    # on its public field names.
    assert isinstance(get_license_notice("jangseogak"), LicenseNotice)
