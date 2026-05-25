"""Gemini-backed :class:`LLMAdapter` for ``LLM_PROVIDER=live``.

Implements the two spec §6 contracts against Google's
``generativelanguage.googleapis.com`` REST surface:

* :meth:`generate_recipes` — spec §6.2. ``temperature=0.7`` (creativity),
  ``maxOutputTokens=4000``, ``responseSchema`` enforced so the response
  is parseable JSON every time (target: 99% parsing success). Required
  fields per spec: ``name``, ``ingredients``, ``steps``,
  ``source_attribution``.
* :meth:`translate_classical` — spec §6.1. ``temperature=0.1``
  (consistency), ``maxOutputTokens=2000``, ``responseSchema`` returning
  ``{"modern_korean": "..."}`` so the translation output is structured
  rather than free-form text (consistent with spec rule 5: "JSON 형식으로만
  응답하고 다른 텍스트는 일절 포함하지 않습니다").

We call the REST endpoint with ``httpx`` directly instead of pulling in
the heavyweight ``google-generativeai`` SDK (~grpcio + auth chain),
matching the existing trend-side :class:`LLMExpansionCandidateProvider`
(PR #14). The same ``install_httpx_key_redaction`` filter is installed
so the API key never leaks into ``httpx`` access logs via the
``?key=...`` query param.

Failure isolation: any network / schema / parse error escalates to a
mock fallback so recipe-generate / classical-translation calls stay
available during transient Gemini outages. This mirrors the
heritage-adapter resilience contract (PRs #33 / #35 / #36 / #37 / #38).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.llm.base import (
    GeneratedIngredient,
    GeneratedRecipe,
    GeneratedRecipeStep,
    GenerateRecipesInput,
    LLMAdapter,
)
from app.services.llm.mock import MockLLMAdapter
from app.services.trends._httpx_log_redact import (
    install_httpx_key_redaction,
    redact_key_in_url,
)

logger = logging.getLogger(__name__)

_GENERATE_PATH = "/v1beta/models/{model}:generateContent"
_DEFAULT_MODEL = "gemini-2.5-pro"
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_DEFAULT_RECIPE_MAX_TOKENS = 4000
_DEFAULT_TRANSLATE_MAX_TOKENS = 2000
_DEFAULT_RECIPE_TEMPERATURE = 0.7
_DEFAULT_TRANSLATE_TEMPERATURE = 0.1
_DEFAULT_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Response schemas — enforced by Gemini's ``generationConfig.responseSchema``.
# Required-field lists target spec §6.2.1 Step 3: "필수 필드 누락률 0%".
# ---------------------------------------------------------------------------

_INGREDIENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "amount": {"type": "STRING"},
        "note": {"type": "STRING"},
    },
    "required": ["name", "amount"],
}

_STEP_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "description": {"type": "STRING"},
        "waiting": {"type": "BOOLEAN"},
    },
    "required": ["title", "description"],
}

_RECIPE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "description": {"type": "STRING"},
        "region": {"type": "STRING"},
        "era": {"type": "STRING"},
        "diet": {"type": "STRING"},
        "menu_type": {"type": "STRING"},
        "keyword": {"type": "STRING"},
        "difficulty": {"type": "STRING"},
        "time_minutes": {"type": "INTEGER"},
        "servings": {"type": "INTEGER"},
        "estimated_cost_krw": {"type": "INTEGER"},
        "estimated_price_krw": {"type": "INTEGER"},
        "ingredients": {"type": "ARRAY", "items": _INGREDIENT_SCHEMA},
        "steps": {"type": "ARRAY", "items": _STEP_SCHEMA},
        "sns_caption": {"type": "STRING"},
        "source_attribution": {"type": "STRING"},
        "image_url": {"type": "STRING"},
        "is_recommended": {"type": "BOOLEAN"},
    },
    "required": [
        "name",
        "description",
        "region",
        "era",
        "diet",
        "menu_type",
        "keyword",
        "difficulty",
        "time_minutes",
        "servings",
        "estimated_cost_krw",
        "estimated_price_krw",
        "ingredients",
        "steps",
        "sns_caption",
        "source_attribution",
    ],
}

_GENERATE_RECIPES_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "candidates": {"type": "ARRAY", "items": _RECIPE_SCHEMA},
    },
    "required": ["candidates"],
}

_TRANSLATE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {"modern_korean": {"type": "STRING"}},
    "required": ["modern_korean"],
}


class GeminiAPIError(RuntimeError):
    """Raised on any Gemini transport / parse / schema failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeminiLLMAdapter(LLMAdapter):
    """Live Gemini :class:`LLMAdapter` with mock fallback on upstream failure.

    Failure modes that escalate to the mock fallback:

    * Non-200 HTTP status (auth, rate-limit, server error)
    * Transport errors (timeout, connection reset, DNS)
    * Unparseable JSON in ``candidates[0].content.parts[0].text``
    * ``responseSchema`` violation — the parsed JSON is missing a
      required field or has the wrong primitive type
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        recipe_max_tokens: int = _DEFAULT_RECIPE_MAX_TOKENS,
        translate_max_tokens: int = _DEFAULT_TRANSLATE_MAX_TOKENS,
        recipe_temperature: float = _DEFAULT_RECIPE_TEMPERATURE,
        translate_temperature: float = _DEFAULT_TRANSLATE_TEMPERATURE,
        fallback: LLMAdapter | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=live. "
                "Set the env var or switch to LLM_PROVIDER=mock."
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._recipe_max_tokens = recipe_max_tokens
        self._translate_max_tokens = translate_max_tokens
        self._recipe_temperature = recipe_temperature
        self._translate_temperature = translate_temperature
        self._fallback = fallback or MockLLMAdapter()
        # Strip the ``?key=...`` query param from ``httpx`` access logs
        # so the API key never leaks via INFO logging. Idempotent —
        # safe across repeated constructions in long-running processes.
        install_httpx_key_redaction()

    # ----------------------------------------------------------- generate

    def generate_recipes(self, payload: GenerateRecipesInput) -> list[GeneratedRecipe]:
        prompt = build_recipe_prompt(payload)
        try:
            decoded = self._invoke(
                prompt,
                response_schema=_GENERATE_RECIPES_RESPONSE_SCHEMA,
                max_tokens=self._recipe_max_tokens,
                temperature=self._recipe_temperature,
            )
            recipes = _parse_recipes(decoded)
        except GeminiAPIError as exc:
            logger.warning(
                "gemini generate_recipes failed (%s); falling back to mock",
                redact_key_in_url(str(exc)),
            )
            return self._fallback.generate_recipes(payload)
        return recipes

    # ----------------------------------------------------------- translate

    def translate_classical(self, original: str) -> str:
        prompt = build_translate_prompt(original)
        try:
            decoded = self._invoke(
                prompt,
                response_schema=_TRANSLATE_RESPONSE_SCHEMA,
                max_tokens=self._translate_max_tokens,
                temperature=self._translate_temperature,
            )
            modern = decoded.get("modern_korean")
            if not isinstance(modern, str) or not modern.strip():
                raise GeminiAPIError("translate response missing 'modern_korean' string")
        except GeminiAPIError as exc:
            logger.warning(
                "gemini translate_classical failed (%s); falling back to mock",
                redact_key_in_url(str(exc)),
            )
            return self._fallback.translate_classical(original)
        return modern

    # ----------------------------------------------------------- transport

    def _invoke(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any],
        max_tokens: int,
        temperature: float,
    ) -> Any:
        url = f"{self._base_url}{_GENERATE_PATH.format(model=self._model)}"
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=body, params={"key": self._api_key})
        except httpx.HTTPError as exc:
            raise GeminiAPIError(f"transport error: {exc}") from exc
        if resp.status_code != 200:
            raise GeminiAPIError(
                f"Gemini returned {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GeminiAPIError(f"non-JSON Gemini response: {exc}") from exc
        return _extract_payload_text(payload)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def build_recipe_prompt(payload: GenerateRecipesInput) -> str:
    """Korean prompt asking Gemini for exactly 3 recipe candidates.

    Spec §6.2 says ``response_schema`` is enforced and JSON parsing must
    succeed ≥ 99% of the time; both are configured upstream — the prompt
    itself focuses on grounding (matched_documents are listed verbatim so
    Gemini cites them in ``source_attribution``) and on the
    region/diet/menu_type constraints from the request.
    """
    docs_lines = []
    for i, doc in enumerate(payload.matched_documents[:5]):
        title = (doc.get("title") or "").strip() or "(제목 미상)"
        institution = (doc.get("institution") or "").strip() or "기관 미상"
        year = doc.get("year")
        year_str = f"{year}년" if year else "연대 미상"
        excerpt = (doc.get("original_text") or doc.get("summary") or "").strip()
        if excerpt:
            excerpt = excerpt[:200]
        docs_lines.append(
            f"  [{i + 1}] {title} · {institution} · {year_str}"
            + (f"\n      발췌: {excerpt}" if excerpt else "")
        )
    docs_block = "\n".join(docs_lines) if docs_lines else "  (참고 고문헌 없음)"

    return (
        "당신은 한국 전통 식문화 전문 셰프이자 카페 메뉴 개발자입니다. "
        "아래 고문헌 기반 출처를 근거로 현대 카페에서 판매 가능한 시그니처 "
        "메뉴 후보를 정확히 3개 제안해주세요.\n\n"
        f"요청 키워드: {payload.keyword}\n"
        f"타깃 지역: {payload.region}\n"
        f"식이 옵션: {payload.diet}\n"
        f"메뉴 유형: {payload.menu_type}\n\n"
        "참고 고문헌:\n"
        f"{docs_block}\n\n"
        "응답 규칙:\n"
        "1. 정확히 3개의 후보를 ``candidates`` 배열에 담아 반환합니다.\n"
        "2. 각 후보는 응답 스키마의 모든 필수 필드(name, description, region, "
        "era, diet, menu_type, keyword, difficulty, time_minutes, servings, "
        "estimated_cost_krw, estimated_price_krw, ingredients, steps, "
        "sns_caption, source_attribution)를 포함합니다.\n"
        "3. 첫 번째 후보의 ``is_recommended`` 만 true 로 표시합니다.\n"
        "4. ``source_attribution`` 은 위 고문헌 목록의 항목을 정확히 인용하고 "
        "'출처: ' 접두어로 시작합니다.\n"
        "5. ``time_minutes`` / ``servings`` / ``estimated_cost_krw`` / "
        "``estimated_price_krw`` 는 정수입니다.\n"
        "6. 모든 텍스트는 한국어로 작성합니다.\n"
        "7. JSON 형식으로만 응답하고 다른 텍스트는 포함하지 않습니다."
    )


def build_translate_prompt(original: str) -> str:
    """Korean prompt enforcing spec §6.1's translation rules.

    System-prompt rules (verbatim from spec):

    1. 한자/옛한글 → 현대 표준어
    2. 분량 단위(한 되 / 한 홉 등) → 현대 ml/g 병기
    3. 원문의 맥락(계절, 지역, 용도) 보존
    4. 식재료명 → 현대 명칭 + 원문 명칭을 괄호 안에 병기
    5. JSON 형식으로만 응답
    """
    return (
        "당신은 한국 고문헌 전문 번역가입니다. 아래 원문을 다음 원칙에 따라 "
        "현대 한국어로 번역해주세요.\n\n"
        "원칙:\n"
        "1. 한자 및 옛한글을 현대 표준어로 번역합니다.\n"
        "2. 분량 단위(한 되, 한 홉 등)는 현대 ml/g 단위로 병기합니다.\n"
        "3. 번역 시 원문의 맥락(계절, 지역, 용도)을 최대한 보존합니다.\n"
        "4. 식재료명은 현대 명칭으로 표준화하되 원문 명칭을 괄호 안에 "
        "병기합니다.\n"
        "5. JSON 형식으로만 응답하고 다른 텍스트는 일절 포함하지 않습니다.\n\n"
        '응답 스키마: ``{"modern_korean": <번역문>}``.\n\n'
        f"원문:\n{original}"
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _extract_payload_text(payload: Any) -> Any:
    """Pull the inner JSON object out of the Gemini ``generateContent`` envelope.

    Gemini always wraps the model's reply in
    ``candidates[0].content.parts[0].text`` — with
    ``responseMimeType=application/json`` the inner ``text`` is itself a
    JSON-encoded payload that we still need to parse with
    :func:`json.loads`.
    """
    if not isinstance(payload, dict):
        raise GeminiAPIError("non-object Gemini response")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        # Surface the upstream-blocked / safety-filter cases visibly so
        # operators can distinguish "model refused" from "transport down".
        block_reason = (
            payload.get("promptFeedback", {}).get("blockReason")
            if isinstance(payload.get("promptFeedback"), dict)
            else None
        )
        if block_reason:
            raise GeminiAPIError(f"prompt blocked: {block_reason}")
        raise GeminiAPIError("no candidates in Gemini response")
    first = candidates[0]
    if not isinstance(first, dict):
        raise GeminiAPIError("malformed candidate in Gemini response")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        finish = first.get("finishReason")
        if finish and finish != "STOP":
            raise GeminiAPIError(f"Gemini finished without parts: {finish}")
        raise GeminiAPIError("no parts in Gemini response")
    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    if not isinstance(text, str):
        raise GeminiAPIError("no text in Gemini response")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GeminiAPIError(f"Gemini response text is not valid JSON: {exc}") from exc


def _parse_recipes(decoded: Any) -> list[GeneratedRecipe]:
    """Decode the ``generate_recipes`` JSON object into :class:`GeneratedRecipe`s.

    Each candidate is validated explicitly so the spec §6.2.1 "필수 필드
    누락률 0%" target is enforced at parse time, not silently degraded by
    falling back to default values.
    """
    if not isinstance(decoded, dict):
        raise GeminiAPIError("recipe response is not a JSON object")
    raw_candidates = decoded.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise GeminiAPIError("recipe response has no candidates")
    recipes: list[GeneratedRecipe] = []
    for i, item in enumerate(raw_candidates):
        if not isinstance(item, dict):
            raise GeminiAPIError(f"candidate {i} is not a JSON object")
        try:
            recipes.append(_parse_single_recipe(item))
        except (KeyError, TypeError, ValueError) as exc:
            raise GeminiAPIError(f"candidate {i} validation failed: {exc}") from exc
    return recipes


def _parse_single_recipe(item: dict[str, Any]) -> GeneratedRecipe:
    return GeneratedRecipe(
        name=_require_str(item, "name"),
        description=_require_str(item, "description"),
        region=_require_str(item, "region"),
        era=_require_str(item, "era"),
        diet=_require_str(item, "diet"),
        menu_type=_require_str(item, "menu_type"),
        keyword=_require_str(item, "keyword"),
        difficulty=_require_str(item, "difficulty"),
        time_minutes=_require_int(item, "time_minutes"),
        servings=_require_int(item, "servings"),
        estimated_cost_krw=_require_int(item, "estimated_cost_krw"),
        estimated_price_krw=_require_int(item, "estimated_price_krw"),
        ingredients=_parse_ingredients(item.get("ingredients")),
        steps=_parse_steps(item.get("steps")),
        sns_caption=_require_str(item, "sns_caption"),
        source_attribution=_require_str(item, "source_attribution"),
        image_url=str(item.get("image_url") or ""),
        is_recommended=bool(item.get("is_recommended", False)),
    )


def _parse_ingredients(raw: Any) -> list[GeneratedIngredient]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("ingredients must be a non-empty array")
    out: list[GeneratedIngredient] = []
    for j, ing in enumerate(raw):
        if not isinstance(ing, dict):
            raise ValueError(f"ingredient {j} is not an object")
        out.append(
            GeneratedIngredient(
                name=_require_str(ing, "name"),
                amount=_require_str(ing, "amount"),
                note=str(ing.get("note") or ""),
            )
        )
    return out


def _parse_steps(raw: Any) -> list[GeneratedRecipeStep]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("steps must be a non-empty array")
    out: list[GeneratedRecipeStep] = []
    for j, step in enumerate(raw):
        if not isinstance(step, dict):
            raise ValueError(f"step {j} is not an object")
        out.append(
            GeneratedRecipeStep(
                title=_require_str(step, "title"),
                description=_require_str(step, "description"),
                waiting=bool(step.get("waiting", False)),
            )
        )
    return out


def _require_str(obj: dict[str, Any], key: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val:
        raise ValueError(f"missing or non-string field {key!r}")
    return val


def _require_int(obj: dict[str, Any], key: str) -> int:
    val = obj.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        # Gemini sometimes returns ints inside JSON floats; accept those
        # too provided they're whole numbers (e.g. ``20.0`` from a JSON
        # number literal). Reject booleans (Python bool ⊂ int) explicitly.
        if isinstance(val, float) and val.is_integer():
            return int(val)
        raise ValueError(f"field {key!r} is not an integer: {val!r}")
    return val
