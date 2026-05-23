"""Default keyword watchlist for the trend collection job.

Kept as a module-level constant so both the seed and the refresh job (and any
future scheduler) pull from the same list. Twenty entries — the seed's
``_TOP_KEYWORDS`` was the source of truth before, this is the rebranded
single source.
"""

DEFAULT_WATCHLIST: list[str] = [
    "쑥라떼",
    "오미자에이드",
    "흑임자크림",
    "매실청소다",
    "인절미케이크",
    "한방차라떼",
    "전통찻집",
    "곶감스무디",
    "유자청티",
    "대추차",
    "호박죽라떼",
    "미숫가루",
    "식혜빙수",
    "생강차",
    "수정과",
    "떡카페",
    "약과디저트",
    "전통병과",
    "한과세트",
    "옛날과자",
]
