"""Deterministic mock LLM that returns 3 plausible recipe candidates.

This is used for local development, CI, and any environment that doesn't have
a Gemini API key. Outputs are derived from inputs (keyword/region/diet) so
the same request always produces the same recipes.
"""

from __future__ import annotations

import hashlib

from app.services.licensing import format_attribution
from app.services.llm.base import (
    GeneratedIngredient,
    GeneratedRecipe,
    GeneratedRecipeStep,
    GenerateRecipesInput,
    LLMAdapter,
)

_UNSPLASH_IMAGES = [
    "https://images.unsplash.com/photo-1515823064-d6e0c04616a7?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=800",
    "https://images.unsplash.com/photo-1589698272390-0501a07619bb?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=800",
    "https://images.unsplash.com/photo-1671762520613-af74d6268101?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=800",
]

_DIFFICULTIES = ["쉬움", "보통", "쉬움"]
_TIMES = [15, 20, 10]
_COSTS = [1200, 1450, 980]
_PRICES = [5500, 6500, 4800]


def _seed_int(payload: GenerateRecipesInput, salt: str) -> int:
    raw = f"{payload.keyword}|{payload.region}|{payload.diet}|{payload.menu_type}|{salt}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def _doc_source(payload: GenerateRecipesInput, index: int) -> str:
    """Build the spec-§3.1 attribution string for a mock recipe.

    Routes through :func:`~app.services.licensing.format_attribution`
    so the mock emits the same KOGL-1-compliant shape ("출처: 음식디미
    방 (1670) · 한국학중앙연구원 장서각") as the live Gemini adapter.
    That keeps the structured ``license_notice`` reverse-lookup happy
    and means the mock and the live path render identically in PDF /
    SNS outputs.
    """
    if payload.matched_documents and index < len(payload.matched_documents):
        doc = payload.matched_documents[index]
        return format_attribution(
            doc.get("institution", ""),
            title=doc.get("title", ""),
            year=doc.get("year"),
        )
    return "출처: 공공누리 제1유형 데이터"


class MockLLMAdapter(LLMAdapter):
    """Returns 3 candidates derived deterministically from input."""

    def generate_recipes(self, payload: GenerateRecipesInput) -> list[GeneratedRecipe]:
        kw = payload.keyword.replace("#", "")
        candidates: list[GeneratedRecipe] = []

        templates = [
            {
                "name_fmt": "{region} {kw} 라떼",
                "desc": (
                    "{doc_title}의 조리법을 현대적으로 재해석한 시그니처 음료. "
                    "{kw}의 풍미와 부드러운 크림이 조화를 이룹니다."
                ),
                "menu_kind": "라떼",
            },
            {
                "name_fmt": "{kw} 프라페",
                "desc": (
                    "전통 {kw}을 블렌딩한 시원한 프라페. "
                    "쫄깃한 식감과 부드러운 크림이 어우러진 독특한 음료입니다."
                ),
                "menu_kind": "프라페",
            },
            {
                "name_fmt": "{kw} 한방 스무디",
                "desc": (
                    "{kw}과 전통 한방 재료를 조합한 건강 스무디. "
                    "대추, 생강 등이 더해져 따뜻한 성질을 가진 웰빙 음료입니다."
                ),
                "menu_kind": "스무디",
            },
        ]

        doc_title = (
            payload.matched_documents[0].get("title")
            if payload.matched_documents
            else "전통 고문헌"
        )

        for i, tmpl in enumerate(templates):
            seed = _seed_int(payload, str(i))
            recipe = GeneratedRecipe(
                name=tmpl["name_fmt"].format(region=payload.region, kw=kw),
                description=tmpl["desc"].format(doc_title=doc_title, kw=kw),
                region=payload.region,
                era=_pick_era(seed),
                diet=payload.diet,
                menu_type=payload.menu_type,
                keyword=kw,
                difficulty=_DIFFICULTIES[i],
                time_minutes=_TIMES[i],
                servings=2,
                estimated_cost_krw=_COSTS[i],
                estimated_price_krw=_PRICES[i],
                ingredients=_make_ingredients(kw, seed),
                steps=_make_steps(kw, tmpl["menu_kind"]),
                sns_caption=_make_sns_caption(kw, payload.region),
                source_attribution=_doc_source(payload, i),
                image_url=_UNSPLASH_IMAGES[i % len(_UNSPLASH_IMAGES)],
                is_recommended=(i == 0),
            )
            candidates.append(recipe)

        return candidates

    def translate_classical(self, original: str) -> str:
        # Deterministic placeholder: in mock mode we just echo the input
        # tagged with a "modern translation" prefix. Real Gemini would translate.
        return f"[현대어 번역(mock)] {original}"


def _pick_era(seed: int) -> str:
    eras = ["조선전기", "조선후기", "근대"]
    return eras[seed % len(eras)]


def _make_ingredients(kw: str, seed: int) -> list[GeneratedIngredient]:
    base = [
        GeneratedIngredient(name=f"생{kw}", amount="30g"),
        GeneratedIngredient(name="인절미 크림", amount="80ml"),
        GeneratedIngredient(name="오트밀크", amount="200ml"),
        GeneratedIngredient(name="흑당시럽", amount="15ml"),
        GeneratedIngredient(name="얼음", amount="적당량"),
    ]
    if seed % 2 == 0:
        base.append(GeneratedIngredient(name="대추", amount="2알", note="얇게 슬라이스"))
    return base


def _make_steps(kw: str, menu_kind: str) -> list[GeneratedRecipeStep]:
    return [
        GeneratedRecipeStep(
            title=f"{kw} 손질 및 블랜칭",
            description=f"생{kw}을 깨끗이 씻어 끓는 물에 30초간 데친 후 찬물에 헹굽니다.",
        ),
        GeneratedRecipeStep(
            title=f"{kw} 베이스 만들기",
            description=(
                f"데친 {kw}과 오트밀크 100ml를 블렌더에 넣고 곱게 갈아줍니다. "
                "쌉싸름한 맛이 적당히 우러나도록 합니다."
            ),
        ),
        GeneratedRecipeStep(
            title="인절미 크림 준비",
            description="인절미 크림을 거품기로 가볍게 저어 부드러운 질감을 만듭니다.",
            waiting=True,
        ),
        GeneratedRecipeStep(
            title="레이어링",
            description="잔에 얼음을 채우고 베이스를 부은 후 크림을 천천히 올립니다.",
        ),
        GeneratedRecipeStep(
            title="마무리",
            description=f"흑당시럽을 가장자리에 둘러 장식하고 {kw} 가루를 살짝 뿌려 {menu_kind}를 완성합니다.",
        ),
    ]


def _make_sns_caption(kw: str, region: str) -> str:
    return (
        f"🌿 조선시대 고문헌 레시피로 만든 #{region}{kw}\n"
        f"장서각 고문헌을 현대적으로 재해석했어요\n\n"
        f"#한국전통음료 #{kw} #비건디저트 #{region}카페 #고문헌레시피 #전통의현대화"
    )
