"""Open-discovery candidate source: Gemini LLM expansion (source D).

Why
---
Static / Google Trends RSS / Naver News all pull *signals from the wild* —
they observe what real users are searching or what real journalists are
writing. Gemini is the complementary layer: a creative analyst that, given
the current month, proposes (a) novel food keywords it knows about from
its training distribution + grounded context (e.g. "두바이쫀득쿠키",
"마라맛디저트", "흑임자라떼") and (b) **한식 변형 candidates** in the same
breath — "두바이강정", "두바이약과", "탕후루약과" — so when the Datalab
adapter later rates the blended score, the 한식 변형 is already a first-
class watchlist member and not something a human needs to add manually.

Workflow
--------
1. Build a Korean-language prompt parameterised on today's year/month and a
   target keyword count. The prompt explicitly asks for (1) 신상 디저트/음료,
   (2) 전통 한식의 현대적 변주, (3) 해외 트렌드를 한식으로 재해석한 변형
   (the key product intent), and (4) novel 식재료/맛/포맷 콘셉트. It also
   spells out the negative categories the denylist filter would reject
   anyway (정치/스포츠/연예/사고/IT/자동차/부동산/금융), so Gemini doesn't
   waste tokens generating them.
2. POST the prompt to ``generativelanguage.googleapis.com`` with
   ``responseMimeType=application/json`` + a ``responseSchema`` of
   ``ARRAY<STRING>``. This forces Gemini to return a parseable JSON array
   directly, no markdown fences to strip.
3. Decode the array, drop blanks and duplicates, enforce a 2-20 character
   length window, and run each through ``food_filter.is_likely_food_adjacent``
   (PR #13's denylist) as a safety net in case Gemini ignores the negative
   categories in the prompt.

Auth & graceful degradation
---------------------------
Requires ``GEMINI_API_KEY``. Off by default (``TRENDS_OPEN_LLM_ENABLED``)
because, unlike Google Trends RSS and Naver News, every call costs money.
When the key is missing the provider returns ``[]`` without making a
network call. Any HTTP / parse / schema error logs a WARNING and returns
``[]`` so ``MultiSourceDiscovery`` and the wider trend refresh job stay
robust.

REST vs SDK
-----------
We call the Gemini REST endpoint with ``httpx`` directly instead of pulling
in the ``google-generativeai`` SDK (~heavy transitive deps incl. grpcio).
The endpoint surface we need is a single POST, the request/response shapes
are stable, and we already depend on ``httpx`` everywhere else in the
trends stack.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx

from app.services.trends._httpx_log_redact import (
    install_httpx_key_redaction,
    redact_key_in_url,
)
from app.services.trends.food_filter import is_likely_food_adjacent

logger = logging.getLogger(__name__)

_GENERATE_PATH = "/v1beta/models/{model}:generateContent"
_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_TARGET = 30
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_MIN_LEN = 2
_MAX_LEN = 20


class LLMExpansionCandidateProvider:
    """``TrendCandidateProvider`` that asks Gemini for novel food keywords."""

    name = "llm_expansion"

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = _DEFAULT_MODEL,
        target_count: int = _DEFAULT_TARGET,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or ""
        self._model = model
        self._target_count = max(1, min(100, target_count))
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # ``httpx`` logs every request URL at INFO; the Gemini endpoint
        # carries the API key as a ``key=`` query parameter (header auth
        # is not supported), so without this filter every refresh would
        # write the bare key to stdout. Idempotent — safe across
        # repeated constructions in long-running processes / tests.
        install_httpx_key_redaction()

    def discover_candidates(
        self,
        today: date | None = None,
        limit: int = 50,
    ) -> list[str]:
        if not self._api_key:
            return []
        ref = today or date.today()
        prompt = build_prompt(ref, self._target_count)
        try:
            raw = self._invoke(prompt)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            # ``str(exc)`` from httpx sometimes embeds the full request
            # URL (e.g. ConnectError messages, ``response.text`` snippets
            # from non-200 paths) — pre-redact before logging so the
            # key doesn't sneak through via the ``%s`` arg of *this*
            # WARN log, which the ``httpx`` filter doesn't intercept.
            logger.warning("gemini trend expansion failed: %s", redact_key_in_url(str(exc)))
            return []
        cleaned = _normalise(raw)
        ranked = [kw for kw in cleaned if is_likely_food_adjacent(kw)]
        return ranked[:limit] if limit else ranked

    def _invoke(self, prompt: str) -> list[str]:
        url = f"{self._base_url}{_GENERATE_PATH.format(model=self._model)}"
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                },
                "temperature": 0.5,
            },
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=body, params={"key": self._api_key})
        if resp.status_code != 200:
            raise ValueError(f"Gemini returned {resp.status_code}: {resp.text[:300]}")
        return _parse_response(resp.json())


def build_prompt(today: date, target_count: int) -> str:
    """Korean prompt asking Gemini for emerging food trend keywords.

    Public for tests and for the upcoming admin debug view in PR #16.
    """
    return (
        f"당신은 한국 식문화 트렌드 분석가입니다. {today.year}년 {today.month}월 기준으로 "
        f"한국에서 새롭게 떠오르거나 인기를 끌고 있는 식음료 트렌드 키워드 "
        f"{target_count}개를 추천해주세요.\n\n"
        "추천 기준:\n"
        "1. 신상 디저트/음료/스낵 (예: 두바이쫀득쿠키, 마라맛디저트, 흑임자라떼)\n"
        "2. 전통 한식의 현대적 변주 (예: 약과아이스크림, 흑임자크림빵, 송편브륄레)\n"
        "3. 해외 식음 트렌드를 한식으로 재해석한 변형 (예: 두바이쫀득쿠키가 인기라면 "
        "두바이강정, 두바이약과 같은 한식 변형도 함께 제안)\n"
        "4. 새롭게 부상하는 식재료/맛/포맷 콘셉트 (예: 탕후루, 마라맛, 트러플, 콜라보)\n\n"
        "다음 카테고리는 제외해주세요:\n"
        "- 정치, 스포츠, 연예인, 사건/사고\n"
        "- IT 제품, 자동차, 부동산, 금융\n\n"
        "각 키워드는 2-15자의 한국어 단어 또는 짧은 표현입니다. 중복 없이, 가능한 한 "
        "다양하게 선정해주세요. JSON 배열 형식 (string 배열)만 출력하세요."
    )


def _parse_response(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("non-object Gemini response")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("no candidates in Gemini response")
    first = candidates[0]
    if not isinstance(first, dict):
        raise ValueError("malformed candidate in Gemini response")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise ValueError("no parts in Gemini response")
    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    if not isinstance(text, str):
        raise ValueError("no text in Gemini response")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Gemini response is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"Gemini response is not a JSON array: {data!r}")
    return [item for item in data if isinstance(item, str)]


def _normalise(raw_keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for kw in raw_keywords:
        normalised = kw.strip()
        if not normalised or normalised in seen:
            continue
        if not (_MIN_LEN <= len(normalised) <= _MAX_LEN):
            continue
        seen.add(normalised)
        out.append(normalised)
    return out
