"""Heritage data adapter factory.

Mock vs live is selected by :attr:`Settings.heritage_provider`. When live,
:attr:`Settings.heritage_live_source` selects which open-API source the
adapter routes through:

* ``jangseogak`` (default) — 장서각 Digital Archive Open API (PR #33).
* ``koreanstudies`` — 한국학자료포털 (한국학중앙연구원) Open API
  (kostma.aks.ac.kr, PR #35).
* ``nlk`` — 국립중앙도서관 Open API (nl.go.kr). **Requires
  ``NLK_API_KEY``** — when the key is missing the factory transparently
  degrades to the mock matcher (with a one-time warning) instead of
  failing recipe-generate at boot.
* ``gihohak`` — 기호유학 고문헌 통합정보시스템 (giho.cnu.ac.kr,
  충남대, PR #37). Fully open (no API key required) like 장서각 and
  한국학자료포털.
* ``multi`` — :class:`MultiSourceHeritageAdapter` fan-in across the
  sources listed in ``HERITAGE_MULTI_SOURCES``
  (default ``jangseogak,koreanstudies,gihohak``). NLK is opt-in here
  because it requires a key; missing-key sources are silently dropped.

See todo.md §1.3.1 for the broader source roadmap; 국사편찬위
(`nihc`) remains the final outstanding source.
"""

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.heritage.base import HeritageAdapter
from app.services.heritage.gihohak import GihohakSearchClient
from app.services.heritage.hybrid import HybridHeritageAdapter
from app.services.heritage.jangseogak import JangseogakSearchClient
from app.services.heritage.koreanstudies import KoreanstudiesSearchClient
from app.services.heritage.live import LiveHeritageAdapter
from app.services.heritage.live_gihohak import LiveGihohakAdapter
from app.services.heritage.live_koreanstudies import LiveKoreanstudiesAdapter
from app.services.heritage.live_nlk import LiveNlkAdapter
from app.services.heritage.mock import MockHeritageAdapter
from app.services.heritage.multi_source import HeritageSource, MultiSourceHeritageAdapter
from app.services.heritage.nlk import NlkSearchClient

logger = logging.getLogger(__name__)


@lru_cache
def get_heritage_adapter() -> HeritageAdapter:
    """Build the heritage adapter chain.

    Two orthogonal axes select what comes out:

    * ``heritage_provider`` (``mock`` | ``live``) — picks the
      *keyword* layer. ``mock`` is the seeded ``MockHeritageAdapter``
      used in tests / local dev; ``live`` routes through one of the
      four open-API single-source adapters or
      :class:`MultiSourceHeritageAdapter` over a fan-in subset.
    * ``heritage_retrieval_mode`` (``keyword`` | ``hybrid``) — wraps
      the keyword layer with :class:`HybridHeritageAdapter` when set
      to ``hybrid``. The hybrid layer also runs
      :meth:`HeritageIndexer.query_all_sources` and blends both
      layers' results. Requires no extra credentials beyond what the
      keyword layer already needs — if the vector store is mock or
      empty the semantic side contributes nothing and behaviour
      collapses to keyword-only.
    """
    settings = get_settings()
    base = _build_keyword_adapter(settings)
    if settings.heritage_retrieval_mode != "hybrid":
        return base
    return _wrap_hybrid(base, settings)


def get_keyword_heritage_adapter() -> HeritageAdapter:
    """Return the *keyword-only* heritage adapter, bypassing the hybrid wrap.

    Backfill / indexing jobs use this so the semantic side of hybrid
    retrieval (which depends on the vector index being populated) does
    not recurse during the population step. Same provider routing as
    :func:`get_heritage_adapter`, minus the
    :class:`HybridHeritageAdapter` wrapper.
    """
    return _build_keyword_adapter(get_settings())


def _build_keyword_adapter(settings: Settings) -> HeritageAdapter:
    """Return the keyword (non-hybrid) heritage adapter for ``settings``."""
    if settings.heritage_provider != "live":
        return MockHeritageAdapter()

    if settings.heritage_live_source == "koreanstudies":
        client = KoreanstudiesSearchClient(base_url=settings.koreanstudies_base_url)
        return LiveKoreanstudiesAdapter(client=client)

    if settings.heritage_live_source == "nlk":
        # NLK is the first source that requires an API key. Rather than
        # raising on boot when the key is missing, degrade gracefully to
        # the mock matcher so recipe-generate keeps working — the user can
        # set NLK_API_KEY later without restarting just because the key is
        # absent. The actual `NlkSearchClient` constructor still validates
        # the key (so misconfigurations surface loudly in tests).
        if not settings.nlk_api_key:
            return MockHeritageAdapter()
        nlk_client = NlkSearchClient(
            api_key=settings.nlk_api_key,
            base_url=settings.nlk_base_url,
        )
        return LiveNlkAdapter(client=nlk_client)

    if settings.heritage_live_source == "gihohak":
        gihohak_client = GihohakSearchClient(base_url=settings.gihohak_base_url)
        return LiveGihohakAdapter(client=gihohak_client)

    if settings.heritage_live_source == "multi":
        return _build_multi_source_adapter(settings)

    # Default branch: jangseogak. Keep this as the explicit fallback so
    # any future un-handled Literal value loudly degrades to the most
    # battle-tested adapter rather than silently breaking recipe-generate.
    client = JangseogakSearchClient(base_url=settings.jangseogak_base_url)
    return LiveHeritageAdapter(client=client)


def _build_multi_source_adapter(settings: Settings) -> HeritageAdapter:
    """Build a :class:`MultiSourceHeritageAdapter` from the configured source list.

    Sources requiring credentials that aren't provisioned (currently only
    NLK) are silently skipped with a warning rather than failing boot —
    same graceful-degrade contract as the single-source ``nlk`` branch.
    Unknown source names are likewise skipped + warned. If every requested
    source is filtered out, we fall back to :class:`MockHeritageAdapter`
    so recipe-generate stays available.
    """
    requested = settings.heritage_multi_sources_list
    sources: list[HeritageSource] = []
    for name in requested:
        if name == "jangseogak":
            sources.append(
                HeritageSource(
                    "jangseogak",
                    LiveHeritageAdapter(
                        client=JangseogakSearchClient(base_url=settings.jangseogak_base_url)
                    ),
                )
            )
        elif name == "koreanstudies":
            sources.append(
                HeritageSource(
                    "koreanstudies",
                    LiveKoreanstudiesAdapter(
                        client=KoreanstudiesSearchClient(base_url=settings.koreanstudies_base_url)
                    ),
                )
            )
        elif name == "nlk":
            if not settings.nlk_api_key:
                logger.warning(
                    "multi-source heritage: %r requested but NLK_API_KEY is unset; skipping",
                    name,
                )
                continue
            sources.append(
                HeritageSource(
                    "nlk",
                    LiveNlkAdapter(
                        client=NlkSearchClient(
                            api_key=settings.nlk_api_key,
                            base_url=settings.nlk_base_url,
                        )
                    ),
                )
            )
        elif name == "gihohak":
            sources.append(
                HeritageSource(
                    "gihohak",
                    LiveGihohakAdapter(
                        client=GihohakSearchClient(base_url=settings.gihohak_base_url)
                    ),
                )
            )
        else:
            logger.warning(
                "multi-source heritage: unknown source %r in HERITAGE_MULTI_SOURCES; skipping",
                name,
            )

    if not sources:
        logger.warning(
            "multi-source heritage: no valid sources configured "
            "(HERITAGE_MULTI_SOURCES=%r); falling back to mock",
            settings.heritage_multi_sources,
        )
        return MockHeritageAdapter()

    return MultiSourceHeritageAdapter(sources=sources)


def _wrap_hybrid(base: HeritageAdapter, settings: Settings) -> HeritageAdapter:
    """Wrap ``base`` with :class:`HybridHeritageAdapter` when hybrid mode is on.

    Imports the vector_search factory locally to keep the import graph
    flat: :mod:`app.services.heritage` is imported very early during
    FastAPI route registration, and vector_search transitively imports
    httpx + the Vertex modules. Local import lets ``keyword`` mode
    skip that cost entirely.
    """
    from app.services.embeddings import get_embedding_adapter
    from app.services.vector_search import (
        HeritageIndexer,
        get_vector_search_adapter,
    )

    indexer = HeritageIndexer(
        embedder=get_embedding_adapter(),
        vector_store=get_vector_search_adapter(),
    )
    logger.info(
        "heritage hybrid retrieval enabled (keyword_weight=%.2f, semantic_top_k=%d, namespaces=%r)",
        settings.heritage_hybrid_keyword_weight,
        settings.heritage_hybrid_semantic_top_k,
        indexer.allowed_namespaces,
    )
    return HybridHeritageAdapter(
        keyword_adapter=base,
        indexer=indexer,
        keyword_weight=settings.heritage_hybrid_keyword_weight,
        semantic_top_k=settings.heritage_hybrid_semantic_top_k,
    )


__all__ = [
    "HeritageAdapter",
    "HeritageSource",
    "HybridHeritageAdapter",
    "LiveGihohakAdapter",
    "LiveHeritageAdapter",
    "LiveKoreanstudiesAdapter",
    "LiveNlkAdapter",
    "MockHeritageAdapter",
    "MultiSourceHeritageAdapter",
    "get_heritage_adapter",
    "get_keyword_heritage_adapter",
]
