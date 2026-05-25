"""Tests for :class:`GeminiLLMAdapter` and the ``live`` LLM factory branch."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.llm import get_llm_adapter
from app.services.llm.base import GenerateRecipesInput
from app.services.llm.gemini import (
    GeminiAPIError,
    GeminiLLMAdapter,
    _extract_payload_text,
    _parse_recipes,
    build_recipe_prompt,
    build_translate_prompt,
)
from app.services.llm.mock import MockLLMAdapter

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _well_formed_recipe(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "쑥라떼",
        "description": "전통 쑥 라떼",
        "region": "충청",
        "era": "조선후기",
        "diet": "vegan",
        "menu_type": "음료",
        "keyword": "쑥",
        "difficulty": "쉬움",
        "time_minutes": 15,
        "servings": 2,
        "estimated_cost_krw": 1200,
        "estimated_price_krw": 5500,
        "ingredients": [
            {"name": "생쑥", "amount": "30g"},
            {"name": "오트밀크", "amount": "200ml", "note": "차갑게"},
        ],
        "steps": [
            {"title": "재료 손질", "description": "쑥을 깨끗이 씻습니다."},
            {"title": "블렌딩", "description": "블렌더로 갈아줍니다.", "waiting": True},
        ],
        "sns_caption": "#쑥라떼 #전통",
        "source_attribution": "출처: 음식디미방 · 장서각",
        "image_url": "https://example.com/img.jpg",
        "is_recommended": True,
    }
    if overrides:
        base.update(overrides)
    return base


def _gemini_payload(inner: Any) -> dict[str, Any]:
    """Wrap an inner JSON object into a Gemini ``generateContent`` envelope."""
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": json.dumps(inner, ensure_ascii=False)}]},
                "finishReason": "STOP",
            }
        ]
    }


def _mock_response(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(body, str):
        resp.text = body
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.text = json.dumps(body, ensure_ascii=False)
        resp.json = MagicMock(return_value=body)
    return resp


def _payload(matched: list[dict] | None = None) -> GenerateRecipesInput:
    return GenerateRecipesInput(
        keyword="쑥",
        region="충청",
        diet="vegan",
        menu_type="음료",
        matched_documents=matched or [],
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_adapter_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        GeminiLLMAdapter(api_key="")


def test_adapter_stores_configuration() -> None:
    a = GeminiLLMAdapter(
        api_key="key",
        model="gemini-2.5-flash",
        base_url="https://example.com/",
        timeout=10.0,
        recipe_max_tokens=2000,
        translate_max_tokens=500,
        recipe_temperature=0.5,
        translate_temperature=0.0,
    )
    # Trailing slash is stripped so we don't end up with a double slash.
    assert a._base_url == "https://example.com"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def test_recipe_prompt_embeds_request_parameters() -> None:
    prompt = build_recipe_prompt(_payload())
    assert "쑥" in prompt
    assert "충청" in prompt
    assert "vegan" in prompt
    assert "음료" in prompt
    assert "candidates" in prompt
    assert "is_recommended" in prompt


def test_recipe_prompt_inlines_matched_documents_for_grounding() -> None:
    docs = [
        {
            "title": "음식디미방",
            "institution": "장서각",
            "year": 1670,
            "summary": "조선후기 한글 조리서",
        }
    ]
    prompt = build_recipe_prompt(_payload(matched=docs))
    assert "음식디미방" in prompt
    assert "장서각" in prompt
    assert "1670년" in prompt
    # Summary surfaces as 발췌 so Gemini grounds its source_attribution on it.
    assert "조선후기 한글 조리서" in prompt


def test_recipe_prompt_caps_documents_to_five() -> None:
    docs = [{"title": f"doc{i}", "institution": "장서각", "year": 1600 + i} for i in range(10)]
    prompt = build_recipe_prompt(_payload(matched=docs))
    assert "doc0" in prompt
    assert "doc4" in prompt
    # 6th+ document excluded so token budget stays bounded.
    assert "doc5" not in prompt
    assert "doc9" not in prompt


def test_recipe_prompt_tolerates_documents_without_year_or_excerpt() -> None:
    docs = [{"title": "음식디미방", "institution": "장서각"}]
    prompt = build_recipe_prompt(_payload(matched=docs))
    assert "음식디미방" in prompt
    assert "연대 미상" in prompt


def test_translate_prompt_embeds_all_five_spec_rules() -> None:
    prompt = build_translate_prompt("원문 텍스트")
    # Verbatim spec §6.1 rule fragments.
    assert "한자 및 옛한글" in prompt
    assert "분량 단위" in prompt
    assert "맥락" in prompt
    assert "식재료명" in prompt
    assert "JSON 형식으로만 응답" in prompt
    assert "원문 텍스트" in prompt
    assert "modern_korean" in prompt


# ---------------------------------------------------------------------------
# _extract_payload_text (envelope parsing)
# ---------------------------------------------------------------------------


def test_extract_payload_unwraps_inner_json() -> None:
    decoded = _extract_payload_text(_gemini_payload({"x": 1}))
    assert decoded == {"x": 1}


def test_extract_payload_raises_on_non_object() -> None:
    with pytest.raises(GeminiAPIError, match="non-object"):
        _extract_payload_text("not a dict")


def test_extract_payload_raises_on_missing_candidates() -> None:
    with pytest.raises(GeminiAPIError, match="no candidates"):
        _extract_payload_text({"candidates": []})


def test_extract_payload_surfaces_safety_block_reason() -> None:
    with pytest.raises(GeminiAPIError, match="prompt blocked: SAFETY"):
        _extract_payload_text({"promptFeedback": {"blockReason": "SAFETY"}})


def test_extract_payload_raises_on_non_stop_finish_with_no_parts() -> None:
    payload = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]}
    with pytest.raises(GeminiAPIError, match="finished without parts: MAX_TOKENS"):
        _extract_payload_text(payload)


def test_extract_payload_raises_on_non_json_text() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "definitely-not-json"}]}}]}
    with pytest.raises(GeminiAPIError, match="not valid JSON"):
        _extract_payload_text(payload)


def test_extract_payload_raises_on_missing_text() -> None:
    payload = {"candidates": [{"content": {"parts": [{"not_text": "x"}]}}]}
    with pytest.raises(GeminiAPIError, match="no text"):
        _extract_payload_text(payload)


# ---------------------------------------------------------------------------
# _parse_recipes (schema validation)
# ---------------------------------------------------------------------------


def test_parse_recipes_happy_path() -> None:
    recipes = _parse_recipes({"candidates": [_well_formed_recipe()]})
    assert len(recipes) == 1
    r = recipes[0]
    assert r.name == "쑥라떼"
    assert r.time_minutes == 15
    assert r.servings == 2
    assert r.is_recommended is True
    assert len(r.ingredients) == 2
    assert r.ingredients[0].name == "생쑥"
    assert r.ingredients[1].note == "차갑게"
    assert r.steps[1].waiting is True


def test_parse_recipes_accepts_integer_valued_floats() -> None:
    """Gemini occasionally returns ``20.0`` for an INTEGER field."""
    payload = {"candidates": [_well_formed_recipe({"time_minutes": 20.0})]}
    recipes = _parse_recipes(payload)
    assert recipes[0].time_minutes == 20


def test_parse_recipes_rejects_non_object_response() -> None:
    with pytest.raises(GeminiAPIError, match="not a JSON object"):
        _parse_recipes(["not", "an", "object"])


def test_parse_recipes_rejects_missing_candidates() -> None:
    with pytest.raises(GeminiAPIError, match="no candidates"):
        _parse_recipes({"candidates": []})


def test_parse_recipes_rejects_missing_required_string_field() -> None:
    bad = _well_formed_recipe()
    del bad["name"]
    with pytest.raises(GeminiAPIError, match="missing or non-string field 'name'"):
        _parse_recipes({"candidates": [bad]})


def test_parse_recipes_rejects_non_integer_time_minutes() -> None:
    bad = _well_formed_recipe({"time_minutes": "fifteen"})
    with pytest.raises(GeminiAPIError, match="field 'time_minutes' is not an integer"):
        _parse_recipes({"candidates": [bad]})


def test_parse_recipes_rejects_boolean_in_integer_field() -> None:
    """Booleans are technically ints in Python — verify they're rejected."""
    bad = _well_formed_recipe({"servings": True})
    with pytest.raises(GeminiAPIError, match="field 'servings' is not an integer"):
        _parse_recipes({"candidates": [bad]})


def test_parse_recipes_rejects_empty_ingredients() -> None:
    bad = _well_formed_recipe({"ingredients": []})
    with pytest.raises(GeminiAPIError, match="non-empty array"):
        _parse_recipes({"candidates": [bad]})


def test_parse_recipes_rejects_empty_steps() -> None:
    bad = _well_formed_recipe({"steps": []})
    with pytest.raises(GeminiAPIError, match="non-empty array"):
        _parse_recipes({"candidates": [bad]})


def test_parse_recipes_rejects_non_object_candidate() -> None:
    with pytest.raises(GeminiAPIError, match="candidate 0 is not a JSON object"):
        _parse_recipes({"candidates": ["not an object"]})


def test_parse_recipes_default_image_and_recommended() -> None:
    """``image_url`` / ``is_recommended`` are optional in the schema."""
    minimal = _well_formed_recipe()
    del minimal["image_url"]
    del minimal["is_recommended"]
    recipes = _parse_recipes({"candidates": [minimal]})
    assert recipes[0].image_url == ""
    assert recipes[0].is_recommended is False


# ---------------------------------------------------------------------------
# generate_recipes — end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


def test_generate_recipes_returns_three_candidates() -> None:
    a = GeminiLLMAdapter(api_key="key")
    inner = {"candidates": [_well_formed_recipe() for _ in range(3)]}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload(inner))
        recipes = a.generate_recipes(_payload())
    assert len(recipes) == 3
    assert all(r.name == "쑥라떼" for r in recipes)


def test_generate_recipes_request_shape() -> None:
    a = GeminiLLMAdapter(api_key="abc-123", model="gemini-2.5-pro")
    inner = {"candidates": [_well_formed_recipe()]}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload(inner))
        a.generate_recipes(_payload())

    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert "gemini-2.5-pro:generateContent" in url
    assert kwargs["params"]["key"] == "abc-123"
    body = kwargs["json"]
    gen = body["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert gen["temperature"] == 0.7
    assert gen["maxOutputTokens"] == 4000
    # Recipe response schema enforced (OBJECT with `candidates` array).
    assert gen["responseSchema"]["type"] == "OBJECT"
    assert "candidates" in gen["responseSchema"]["properties"]


def test_generate_recipes_falls_back_to_mock_on_non_200() -> None:
    a = GeminiLLMAdapter(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(500, {"error": "boom"})
        result = a.generate_recipes(_payload())
    # Mock returns exactly 3 candidates.
    assert len(result) == 3


def test_generate_recipes_falls_back_on_transport_error() -> None:
    a = GeminiLLMAdapter(api_key="key")
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("nope")):
        result = a.generate_recipes(_payload())
    assert len(result) == 3


def test_generate_recipes_falls_back_on_schema_violation() -> None:
    a = GeminiLLMAdapter(api_key="key")
    bad = _well_formed_recipe()
    del bad["source_attribution"]
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload({"candidates": [bad]}))
        result = a.generate_recipes(_payload())
    # Mock fallback engaged → 3 deterministic candidates.
    assert len(result) == 3


def test_generate_recipes_falls_back_on_malformed_envelope() -> None:
    a = GeminiLLMAdapter(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"candidates": []})
        result = a.generate_recipes(_payload())
    assert len(result) == 3


def test_generate_recipes_uses_custom_fallback_when_provided() -> None:
    """``fallback=`` lets callers swap in any LLMAdapter (e.g. a stricter
    fail-loud mock for staging)."""
    fallback = MagicMock(spec=MockLLMAdapter)
    fallback.generate_recipes.return_value = ["sentinel"]  # type: ignore[list-item]
    a = GeminiLLMAdapter(api_key="key", fallback=fallback)
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(500, {"error": "nope"})
        result = a.generate_recipes(_payload())
    assert result == ["sentinel"]
    fallback.generate_recipes.assert_called_once()


# ---------------------------------------------------------------------------
# translate_classical — end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


def test_translate_classical_returns_modern_korean() -> None:
    a = GeminiLLMAdapter(api_key="key")
    inner = {"modern_korean": "쑥을 끓는 물에 넣어 우려낸다."}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload(inner))
        translated = a.translate_classical("艾草煎水")
    assert translated == "쑥을 끓는 물에 넣어 우려낸다."


def test_translate_classical_request_shape() -> None:
    a = GeminiLLMAdapter(api_key="key")
    inner = {"modern_korean": "x"}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload(inner))
        a.translate_classical("원문")
    body = post.call_args.kwargs["json"]
    gen = body["generationConfig"]
    # Spec §6.1: temperature 0.1, max_tokens 2000.
    assert gen["temperature"] == 0.1
    assert gen["maxOutputTokens"] == 2000
    schema = gen["responseSchema"]
    assert schema["properties"]["modern_korean"]["type"] == "STRING"
    assert schema["required"] == ["modern_korean"]


def test_translate_classical_falls_back_to_mock_on_non_200() -> None:
    a = GeminiLLMAdapter(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(500, {"error": "boom"})
        result = a.translate_classical("원문")
    # MockLLMAdapter echoes the input with a [현대어 번역(mock)] prefix.
    assert result.startswith("[현대어 번역(mock)]")
    assert "원문" in result


def test_translate_classical_falls_back_on_missing_field() -> None:
    a = GeminiLLMAdapter(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload({"wrong": "x"}))
        result = a.translate_classical("원문")
    assert result.startswith("[현대어 번역(mock)]")


def test_translate_classical_falls_back_on_empty_string() -> None:
    """Schema-compliant but semantically empty — fallback so callers always
    get usable output."""
    a = GeminiLLMAdapter(api_key="key")
    inner = {"modern_korean": "   "}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload(inner))
        result = a.translate_classical("원문")
    assert result.startswith("[현대어 번역(mock)]")


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def _reset_caches() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_llm_adapter.cache_clear()


def test_factory_returns_mock_when_provider_is_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    _reset_caches()
    assert isinstance(get_llm_adapter(), MockLLMAdapter)


def test_factory_returns_mock_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "live")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _reset_caches()
    assert isinstance(get_llm_adapter(), MockLLMAdapter)


def test_factory_returns_gemini_adapter_when_live_and_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "live")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _reset_caches()
    adapter = get_llm_adapter()
    assert isinstance(adapter, GeminiLLMAdapter)


def test_factory_honours_gemini_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "live")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://staging.example/")
    monkeypatch.setenv("GEMINI_RECIPE_TEMPERATURE", "0.5")
    _reset_caches()
    adapter = get_llm_adapter()
    assert isinstance(adapter, GeminiLLMAdapter)
    assert adapter._model == "gemini-2.5-flash"  # type: ignore[attr-defined]
    assert adapter._base_url == "https://staging.example"  # type: ignore[attr-defined]
    assert adapter._recipe_temperature == 0.5  # type: ignore[attr-defined]
