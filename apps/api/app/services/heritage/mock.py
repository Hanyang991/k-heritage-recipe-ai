"""Mock heritage adapter — returns the 3 sample documents from the tech spec.

When swapped for the live adapter, the search() interface stays identical.
"""

from __future__ import annotations

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc

_SEEDED: list[HeritageDoc] = [
    HeritageDoc(
        external_id="jangseogak/eumsikdimibang",
        title="음식디미방",
        institution="jangseogak",
        region="경상도",
        period="조선후기",
        category="조리서",
        year=1670,
        original_text=(
            "쑥의 어린 잎을 깨끗이 씻어 끓는 물에 데친 뒤 찬물에 헹구고 곱게 다져 사용한다. "
            "꿀과 잣가루를 더하여 단맛과 고소함을 더한다."
        ),
        summary="경상도 장계향 저술. 한국 최초의 한글 조리서로 알려져 있으며 다양한 전통 음식 조리법을 수록.",
        license="KOGL-1",
    ),
    HeritageDoc(
        external_id="nfm/gyuhapchongseo",
        title="규합총서",
        institution="nfm",
        region="전국",
        period="조선후기",
        category="조리서",
        year=1809,
        original_text=(
            "오미자를 깨끗이 씻어 차게 우려낸 물을 사용한다. "
            "꿀이나 시럽을 더하여 시원하게 마시면 갈증을 풀어준다."
        ),
        summary="조선후기 가정에서 사용되던 일상 백과사전. 음식·의복·살림 전반의 지식을 망라.",
        license="KOGL-1",
    ),
    HeritageDoc(
        external_id="culture/jeonju-bevs",
        title="향토음식 DB - 전주 전통음료",
        institution="culture",
        region="전라도",
        period="근대",
        category="향토음식",
        year=None,
        original_text=(
            "전주 지역 전통음료는 콩물, 식혜, 미숫가루 등 곡물 베이스가 주를 이루며 "
            "근래에는 쑥·매실 등을 활용한 변형이 늘고 있다."
        ),
        summary="문화데이터광장에 등재된 전주 향토음료 데이터셋.",
        license="KOGL-1",
    ),
]


def _score(doc: HeritageDoc, keyword: str, region: str | None, period: str | None) -> float:
    score = 0.0
    kw = keyword.replace("#", "").strip()
    if kw and (kw in doc.title or kw in doc.original_text or kw in doc.summary):
        score += 0.6
    if region and region in (doc.region, "전국"):
        score += 0.25
    if period and period == doc.period:
        score += 0.15
    return min(score, 1.0)


class MockHeritageAdapter(HeritageAdapter):
    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        scored = [
            DocumentMatch(document=doc, match_score=_score(doc, keyword, region, period))
            for doc in _SEEDED
        ]
        # Bias the leader so the demo always shows a strong top match
        leader_default_scores = (0.94, 0.87, 0.71)
        if all(m.match_score == 0 for m in scored):
            for m, s in zip(scored, leader_default_scores, strict=False):
                m.match_score = s
        scored.sort(key=lambda m: m.match_score, reverse=True)
        return scored[:limit]

    def list_seeded(self) -> list[HeritageDoc]:
        return list(_SEEDED)
