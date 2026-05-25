"""``MultiSourceHeritageAdapter`` — fan-in over multiple ``HeritageAdapter`` sources.

Sibling to :class:`MultiSourceDiscovery` (trends pipeline, PR #15) — same
resilience contract, applied to the heritage-document side:

1. **Fan out**: call every configured ``HeritageAdapter.search`` with the
   same ``(keyword, region, period, limit)`` filters.
2. **Isolate**: any single source's exception is caught + logged; the
   surviving sources still contribute. Only an **all-sources-fail** event
   escalates to the mock matcher (so recipe-generate keeps grounding
   against the seed corpus instead of blowing up the whole request).
3. **Dedupe**: collapse duplicates first by ``(institution, external_id)``
   (intra-source idempotency), then by normalised title (cross-source —
   the same 의궤 / 음식디미방 may surface from both 장서각 and the NLK
   KORCIS catalogue). The higher-scoring entry wins each collision.
4. **Re-rank**: stable sort by ``match_score`` descending. Since all four
   per-source adapters share the same ``0.94 → 0.40`` decay (see
   ``LiveHeritageAdapter`` / ``LiveKoreanstudiesAdapter`` /
   ``LiveNlkAdapter`` / ``LiveGihohakAdapter``) the merged ranking is
   meaningful without renormalising scores.
5. **Trim**: return the top ``limit`` results.

``list_seeded()`` delegates to the mock matcher so the DB seed script
keeps working the same way regardless of which live source is active.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.mock import MockHeritageAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeritageSource:
    """One named source backing :class:`MultiSourceHeritageAdapter`.

    ``name`` is a short stable identifier (matching ``HeritageDoc.institution``
    where possible) — surfaced in log lines so operators can tell which
    upstream just timed out.
    """

    name: str
    adapter: HeritageAdapter


def _normalise_title_for_dedupe(title: str) -> str:
    """Lowercase + drop non-alphanumeric for fuzzy cross-source dedupe.

    Hangul, Han characters, ASCII letters and digits are kept; whitespace,
    punctuation, and bracket marks are stripped. This is intentionally
    aggressive — the goal is to recognise that ``"음식디미방"`` and
    ``"음식 디미방"`` are the same record even when the upstream archives
    format them differently.
    """
    return "".join(ch for ch in title if ch.isalnum()).lower()


class MultiSourceHeritageAdapter:
    """Fan-in across multiple :class:`HeritageAdapter` instances.

    The resilience contract intentionally distinguishes three failure modes
    so the mock-fallback isn't over-eager:

    * **Per-source exception** — isolated, logged, skipped. Surviving
      sources still contribute.
    * **All sources raise** — escalate to the mock fallback. This is the
      production-safety net: recipe-generate must keep working even if
      every upstream is down.
    * **All sources return empty (no exceptions)** — return ``[]``.
      Empty is genuine information; firing the mock here would surface
      irrelevant seeded docs and confuse downstream callers.
    """

    def __init__(
        self,
        sources: list[HeritageSource],
        *,
        fallback: HeritageAdapter | None = None,
    ) -> None:
        if not sources:
            raise ValueError("MultiSourceHeritageAdapter requires at least one source")
        self._sources = list(sources)
        self._fallback = fallback or MockHeritageAdapter()

    @property
    def sources(self) -> list[HeritageSource]:
        return list(self._sources)

    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        all_matches: list[DocumentMatch] = []
        any_succeeded = False

        # Fetch up to `limit` from each source. After dedupe + re-rank we
        # still trim to `limit`, so the union may be larger than `limit`
        # but never smaller than the best single source's contribution.
        for source in self._sources:
            try:
                matches = source.adapter.search(keyword, region=region, period=period, limit=limit)
            except Exception as exc:
                logger.exception(
                    "heritage source %r raised during fan-in; isolating: %s",
                    source.name,
                    exc,
                )
                continue
            any_succeeded = True
            all_matches.extend(matches)

        if not any_succeeded:
            logger.warning(
                "all heritage sources failed during fan-in (keyword=%r); falling back to mock",
                keyword,
            )
            return self._fallback.search(keyword, region=region, period=period, limit=limit)

        if not all_matches:
            # All sources answered but every one returned 0 hits — that's
            # honest information, don't paper over it with seed docs.
            return []

        deduped = _dedupe(all_matches)

        # Stable sort: highest score first; ties broken by title to keep
        # ordering deterministic for tests and recipe-generate.
        deduped.sort(key=lambda m: (-m.match_score, m.document.title))
        return deduped[:limit]

    def list_seeded(self) -> list[HeritageDoc]:
        """Delegate to the mock fallback for seed listing.

        Live mode doesn't change ``app.db.seed``'s behaviour — the seed
        script always uses :class:`MockHeritageAdapter` directly. This
        method exists for protocol compliance only.
        """
        return self._fallback.list_seeded()


def _dedupe(matches: list[DocumentMatch]) -> list[DocumentMatch]:
    """Two-pass dedupe: by ``(institution, external_id)`` then by title.

    Pass 1 collapses intra-source idempotency (same row surfaced twice
    by the same upstream — shouldn't happen but cheap to guard against).
    Pass 2 collapses cross-source duplicates: the same record can legitimately
    surface from multiple archives (장서각 + NLK both index 의궤 holdings,
    for instance). The highest-scoring entry wins each collision.
    """
    by_id: dict[tuple[str, str], DocumentMatch] = {}
    for m in matches:
        key = (m.document.institution, m.document.external_id)
        existing = by_id.get(key)
        if existing is None or m.match_score > existing.match_score:
            by_id[key] = m

    by_title: dict[str, DocumentMatch] = {}
    for m in by_id.values():
        title_key = _normalise_title_for_dedupe(m.document.title)
        if not title_key:
            # Title is all punctuation / empty — don't fuzzy-collapse,
            # fall back to the external_id key (already unique above).
            by_title[f"{m.document.institution}:{m.document.external_id}"] = m
            continue
        existing = by_title.get(title_key)
        if existing is None or m.match_score > existing.match_score:
            by_title[title_key] = m

    return list(by_title.values())
