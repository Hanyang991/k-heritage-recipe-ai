"""Curated K-heritage food keyword pool for the trend discovery layer.

This pool feeds ``CuratedWatchlistDiscovery``: every entry is measured against
the configured ``TrendsAdapter`` (mock in dev/CI, Naver DataLab when
``TRENDS_PROVIDER=live``) and the top-N by blended popularity + rise score is
written to the ``trends`` snapshot. Expanding the pool here is the cheapest
way to add coverage without touching the rest of the pipeline.

When editing:
- Keep entries reasonably specific (1–2 words). Long phrases return ratio 0
  on DataLab.
- Stay within the dessert / drink / snack / 전통과자 domain to match the
  product positioning — full meals (e.g. 비빔밥, 김치찌개) skew the ranking.
- DataLab caps a single request at 5 keywordGroups; growth here just costs
  extra calls per refresh (cap ~1000 calls/day on the free tier — at 80
  keywords / 5 per call = 16 calls per refresh, comfortably within budget).
"""

DEFAULT_WATCHLIST: list[str] = [
    # 음료 & 차 — modern fusion latte
    "쑥라떼",
    "흑임자라떼",
    "인절미라떼",
    "콩가루라떼",
    "미숫가루라떼",
    "식혜라떼",
    "호박죽라떼",
    "한방차라떼",
    # 음료 & 차 — 전통차
    "오미자차",
    "유자청티",
    "대추차",
    "생강차",
    "수정과",
    "식혜",
    "매실차",
    "모과차",
    "둥굴레차",
    "율무차",
    "보리차",
    "헛개차",
    "도라지차",
    "인삼차",
    "결명자차",
    # 음료 & 차 — 에이드/소다
    "오미자에이드",
    "매실청소다",
    "유자에이드",
    # 떡
    "인절미케이크",
    "가래떡",
    "백설기",
    "시루떡",
    "콩떡",
    "쑥떡",
    "송편",
    "절편",
    "화전",
    "흑임자떡",
    "무지개떡",
    "모찌떡",
    "단호박떡",
    "약식",
    "떡카페",
    # 한과 / 전통과자
    "약과",
    "약과디저트",
    "약과아이스크림",
    "약과쿠키",
    "한과세트",
    "옛날과자",
    "다식",
    "강정",
    "정과",
    "매작과",
    "율란",
    "산자",
    "깨강정",
    "송화다식",
    "호두강정",
    "쌀강정",
    # 디저트 퓨전
    "흑임자크림",
    "흑임자아이스크림",
    "흑임자빙수",
    "곶감스무디",
    "곶감초콜릿",
    "식혜빙수",
    "인절미빙수",
    "호박타르트",
    "단호박케이크",
    "단팥크림",
    "유자청케이크",
    "쌀티라미수",
    "콩가루크림",
    "매실시럽",
    # 전통매장 / 베이커리
    "전통찻집",
    "전통병과",
    "한식디저트",
    "전통빵",
    "약과빵",
    "누룽지스낵",
    "누룽지칩",
    "미숫가루쿠키",
]
