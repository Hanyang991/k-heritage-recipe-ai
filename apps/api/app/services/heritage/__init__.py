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

See todo.md §1.3.1 for the broader source roadmap; next additions will
be 국사편찬위 + 기호유학.
"""

from functools import lru_cache

from app.config import get_settings
from app.services.heritage.base import HeritageAdapter
from app.services.heritage.jangseogak import JangseogakSearchClient
from app.services.heritage.koreanstudies import KoreanstudiesSearchClient
from app.services.heritage.live import LiveHeritageAdapter
from app.services.heritage.live_koreanstudies import LiveKoreanstudiesAdapter
from app.services.heritage.live_nlk import LiveNlkAdapter
from app.services.heritage.mock import MockHeritageAdapter
from app.services.heritage.nlk import NlkSearchClient


@lru_cache
def get_heritage_adapter() -> HeritageAdapter:
    settings = get_settings()
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

    # Default branch: jangseogak. Keep this as the explicit fallback so
    # any future un-handled Literal value loudly degrades to the most
    # battle-tested adapter rather than silently breaking recipe-generate.
    client = JangseogakSearchClient(base_url=settings.jangseogak_base_url)
    return LiveHeritageAdapter(client=client)


__all__ = [
    "HeritageAdapter",
    "LiveHeritageAdapter",
    "LiveKoreanstudiesAdapter",
    "LiveNlkAdapter",
    "MockHeritageAdapter",
    "get_heritage_adapter",
]
