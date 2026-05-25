# K-Heritage Recipe AI

Korean heritage recipe generation platform. Search 조선시대 고문헌 → AI(현재는 mock)가 현대화된 레시피 3개를 제안 → 사용자가 저장/PDF/인증서 발급.

This is the **MVP scaffold**: the frontend, the FastAPI backend, the public-API/LLM/Toss adapters, the database schema, and the AI generate pipeline are all wired end-to-end with **mock providers** so the whole app can run without any external API keys. Switching to live providers is a one-flag change once keys are in place.

## Stack

| Layer    | Tech                                                            |
| -------- | --------------------------------------------------------------- |
| Frontend | React 18, Vite 6, TypeScript, Tailwind v4, shadcn/ui, react-router |
| Backend  | FastAPI 0.111+, SQLAlchemy 2.x, Alembic, Pydantic v2, JWT       |
| Data     | PostgreSQL 16 (prod) / SQLite (dev & tests), Redis 7            |
| Infra    | docker-compose, GitHub Actions CI                                |

## Repo layout

```
.
├── apps/
│   ├── web/                React + Vite frontend
│   └── api/                FastAPI backend
│       ├── app/
│       │   ├── routers/    Auth, recipes, trends, documents, payments, admin
│       │   ├── models/     SQLAlchemy ORM
│       │   ├── schemas/    Pydantic request/response models
│       │   ├── services/   LLM / heritage / payments adapters (mock + live)
│       │   ├── auth/       JWT + bcrypt
│       │   └── db/         Session, seed
│       ├── alembic/        Migration scripts
│       └── tests/          pytest
├── docker-compose.yml      postgres + redis + api + web
└── .github/workflows/ci.yml
```

## Quick start (no Docker)

### Backend

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install "bcrypt<4.1"
cp .env.example .env

# Seed sample documents, trends, demo + admin users
python -m app.db.seed

# Run
uvicorn app.main:app --reload
```

API: <http://localhost:8000>  ·  Docs: <http://localhost:8000/v1/docs>

Seeded accounts:

| Role  | Email                    | Password    |
| ----- | ------------------------ | ----------- |
| user  | `demo@k-heritage.app`    | `demo1234`  |
| admin | `admin@k-heritage.app`   | `admin1234` |

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

Web: <http://localhost:5173>  (Vite dev server proxies `/v1/*` to the API.)

## Quick start (Docker)

```bash
docker compose up --build
```

This brings up postgres, redis, the FastAPI app (auto-seeded), and an nginx-served frontend. The web container proxies `/v1/*` to the api container.

| Service | URL                       |
| ------- | ------------------------- |
| Web     | <http://localhost:5173>   |
| API     | <http://localhost:8000>   |
| API docs| <http://localhost:8000/v1/docs> |
| Postgres| `localhost:5432`          |
| Redis   | `localhost:6379`          |

## Tests

```bash
cd apps/api
pytest -v
```

13 happy-path + edge-case tests covering auth, trends, recipe generate / list / detail / delete / PDF / certificate / quota enforcement / admin queue.

## Service modes

| Service   | Env var              | `mock` (default)              | `live`                                       |
| --------- | -------------------- | ----------------------------- | -------------------------------------------- |
| LLM       | `LLM_PROVIDER`       | Deterministic 3 candidates    | Gemini 2.5 Pro — spec §6.1/§6.2 (requires `GEMINI_API_KEY`)   |
| Trends    | `TRENDS_PROVIDER`    | Deterministic ratios          | Naver DataLab (`NAVER_DATALAB_CLIENT_ID/SECRET`) |
| Heritage  | `HERITAGE_PROVIDER`  | 3 seed documents (음식디미방 etc.) | 장서각 + 한국학자료포털 + NLK + 기호유학 (and `multi` fan-in over them) wired; 국사편찬위 deferred |
| Payments  | `PAYMENTS_PROVIDER`  | Always succeeds, fake billing | TossPayments (`TOSS_SECRET_KEY` required)    |

The live LLM adapter (this PR) and the four heritage adapters are fully wired — switching is a single env var change once `GEMINI_API_KEY` is provided. The trends adapter is fully wired live. Live payments are still a scaffold (`NotImplementedError`) pending TossPayments key + merchant registration.

### LLM live mode (`LLM_PROVIDER=live`)

`GeminiLLMAdapter` calls `generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with `httpx` directly (no `google-generativeai` SDK — same call shape as the trend-LLM expansion provider in PR #14). Spec §6 parameters are baked into the defaults:

* **`generate_recipes`** (§6.2) — `temperature=0.7`, `maxOutputTokens=4000`, `responseSchema` enforcing the full `GeneratedRecipe` shape (name / description / region / era / diet / menu_type / keyword / difficulty / time_minutes / servings / estimated_cost_krw / estimated_price_krw / ingredients[] / steps[] / sns_caption / source_attribution all required — satisfies the §6.2.1 Step 3 "필수 필드 누락률 0%" target).
* **`translate_classical`** (§6.1) — `temperature=0.1`, `maxOutputTokens=2000`, `responseSchema` returning `{"modern_korean": "..."}` so the translation output is structured rather than free-form text (consistent with the §6.1 rule: "JSON 형식으로만 응답하고 다른 텍스트는 일체 포함하지 않습니다").

Every failure mode (non-200 status, transport errors, unparseable JSON, schema violations, safety-blocked prompts) escalates to `MockLLMAdapter` so recipe-generate stays available during transient Gemini outages — the same resilience contract as the heritage adapters. The factory also degrades to mock when `LLM_PROVIDER=live` is set but `GEMINI_API_KEY` is unset, with a startup warning, so operators can provision the key later without redeploying.

Overrides (all optional, see `.env.example`): `GEMINI_MODEL`, `GEMINI_BASE_URL`, `GEMINI_REQUEST_TIMEOUT_SECONDS`, `GEMINI_RECIPE_MAX_TOKENS`, `GEMINI_TRANSLATE_MAX_TOKENS`, `GEMINI_RECIPE_TEMPERATURE`, `GEMINI_TRANSLATE_TEMPERATURE`. The `?key=...` URL param is scrubbed from `httpx` access logs by `install_httpx_key_redaction` (idempotent, shared with the trend-LLM path).

### Heritage live adapter (PR #33)

`HERITAGE_PROVIDER=live` now routes through `LiveHeritageAdapter`, which calls the **장서각 Digital Archive Open API** at `GET https://jsg.aks.ac.kr/api/search`. This endpoint is fully open (no API key, no header auth — verified live against the published help page at <https://jsg.aks.ac.kr/api/help>), so the only knob is `JANGSEOGAK_BASE_URL` for pointing at staging mirrors. The response uses Korean field names (`자료명` / `유형분류` / `작성시기` / `청구기호`) which the adapter normalises into the existing `HeritageDoc` shape; `작성시기` is parsed into both a numeric `year` and a coarse `period` bucket (조선전기 ≤ 1592 / 조선후기 1593–1896 / 근대 ≥ 1897) so the recipe-generate prompt's period grounding stays consistent across mock and live. The adapter is resilient: any `JangseogakAPIError` (404, 429, timeout, connect failure, non-JSON body) triggers a graceful fallback to `MockHeritageAdapter`'s seeded matcher rather than failing the whole `/v1/private/recipes/generate` call — empty result sets are kept as-is (a real "the archive has nothing for this query" answer is information, not an error). Spec PDF §3.2 describes a different endpoint (`/api/v1/documents/search` with `q/category/period/page/size` and an API-key header); production traffic uses the live `/api/search` surface and the spec PDF will be refreshed separately.

**Additional heritage sources (planned, todo.md §1.3.1)**: rather than the spec's original 국립민속박물관 + 문화데이터광장 pairing, the project is moving toward four higher-value Korean cultural-heritage open APIs — 한국학자료포털 (한국학중앙연구원, 장서각 자매 포털: 권역별 고문헌 + 용례사전), 국립중앙도서관 (KOLIS-NET / KORCIS 표준 서지), 국사편찬위원회 (인물·연표 메타데이터), 기호유학 고문헌 통합정보시스템 (충남대, 충청 지역 특화). Each will get its own `*Adapter (HeritageAdapter)` + `*SearchClient` under `app/services/heritage/`, then a `MultiSourceHeritageAdapter` fans them in with dedupe + per-source error isolation (same pattern as the trends `MultiSourceDiscovery`).

### Heritage live sources matrix

`HERITAGE_LIVE_SOURCE` selects which open-API source the live adapter routes through. todo.md §1.3.1 is rolling these out incrementally; only 국사편찬위 (« `nihc` », deferred — see todo.md notes) remains outstanding. ``multi`` runs all four (configurable via ``HERITAGE_MULTI_SOURCES``) at once with per-source isolation.

| Value | Adapter | Endpoint | Format | API key |
| --- | --- | --- | --- | --- |
| `jangseogak` (default) | `LiveHeritageAdapter` | `https://jsg.aks.ac.kr/api/search` | JSON | none (open) |
| `koreanstudies` | `LiveKoreanstudiesAdapter` | `https://kostma.aks.ac.kr/OpenAPI/request.aspx` | XML | none (open) |
| `nlk` | `LiveNlkAdapter` | `https://www.nl.go.kr/NL/search/openApi/search.do` | XML | **`NLK_API_KEY` required** |
| `gihohak` | `LiveGihohakAdapter` | `http://giho.cnu.ac.kr/api/literature/search.do` | XML | none (open) |
| `multi` | `MultiSourceHeritageAdapter` | fan-in across `HERITAGE_MULTI_SOURCES` | varies | inherits per source |

**한국학자료포털 (PR #35).** Sister portal to 장서각 — same operating org (한국학중앙연구원), but covers 권역별 (regional) and 민간 (private collections) high-resolution materials instead of the royal archive that 장서각 indexes. The adapter is XML-based (장서각 is JSON), and `KoreanstudiesSearchClient` parses the `<ksm>` envelope into the same `HeritageDoc` shape that recipe-generate already consumes. Region is populated from `작성지역 @현재주소` (a richer signal than 장서각, which doesn't expose 지역 in its search response).

**국립중앙도서관 / NLK (PR #36).** The standardised national-scale source — operator of **KORCIS** (한국고문헌종합목록, federated catalogue of 고전적 across every Korean institution) and **KOLIS-NET** (국가자료종합목록). KORCIS records expose a `control_no` that is stable across institutions, which is what makes NLK the natural dedupe anchor for the planned `MultiSourceHeritageAdapter`. The endpoint requires an API key (apply at <https://www.nl.go.kr/NL/contents/N31101030500.do>, admin approval) — when `NLK_API_KEY` is unset the factory transparently degrades to the mock matcher even with `HERITAGE_LIVE_SOURCE=nlk` set, so recipe-generate stays available while the key is being provisioned. The adapter defaults `category=고문헌` since this is a heritage stack, parses both modern (`"2012"` / `"201201"`) and 고문헌-style (`"순조 14년(1814년)"`) `pub_year_info` shapes, and surfaces upstream `<error_code>` codes (010 / 011 / 012 / 013 / 014) on `NlkAPIError` so auth issues can be distinguished from transient outages in logs.

**기호유학 고문헌 통합정보시스템 (PR #37).** The regional specialist of the four sources. Operated by 충남대 (Chungnam National University) and curated around the 기호유학 (畿湖儒學) school — the Confucian lineage centred on 충청도 + Han River basin gentry / 서원 holdings. Coverage: 고서 (육서심원 포함), 고문서, 금석문, plus an 인물 네트워크 that the other three archives lack. Fully open (no key, no header). The adapter defaults `type=OB` (고서) since classical books carry more food/ritual content than legal/contract documents, parses `<created>` in both `"미상"` and integer-year shapes, and attaches a static `region="충청"` so cross-source region filters route into it — the curation scope is uniform.

All four single-source adapters share identical period bucketing (조선전기 ≤ 1592 / 조선후기 1593–1896 / 근대 ≥ 1897) and identical rank-decay (top hit ≈ 0.94 → floor 0.40), so cross-source result blending will not require renormalising scores. All four degrade gracefully to `MockHeritageAdapter` on transport failures, upstream error envelopes, or unparseable bodies.

**`MultiSourceHeritageAdapter` (this PR).** Fan-in across the configured `HERITAGE_MULTI_SOURCES`. Mirrors the trends-side `MultiSourceDiscovery` (PR #15) resilience contract: a single source's exception is caught + logged but the surviving sources still contribute; only an **all-sources-fail** event escalates to the mock matcher. Empty responses (every source answered, none had hits) return `[]` honestly rather than papering over with seeds. Two-pass dedupe: first by `(institution, external_id)` to absorb intra-source idempotency, then by normalised title (whitespace-stripped + lowercased) to collapse cross-source duplicates such as 의궤 holdings that surface from both 장서각 and NLK’s KORCIS catalogue. The higher-scoring entry wins each collision. NLK is opt-in (excluded from the default `HERITAGE_MULTI_SOURCES=jangseogak,koreanstudies,gihohak`) because it requires `NLK_API_KEY` — add it to the list once the key is provisioned. Unknown source names + unauthenticated sources are silently skipped + warned at boot; if every requested source is filtered out the factory falls back to `MockHeritageAdapter`.

### Vertex AI Vector Search — per-source namespace indexing

Semantic retrieval over the heritage corpus is built on Vertex AI Vector Search with **one index per source** (jangseogak / koreanstudies / nlk / gihohak / nihc) — a deliberate continuation of the heritage layer's per-source isolation contract so KOGL attribution stays clean and operators can rebuild or retire one source's index without touching the others.

| Service | Env var | `mock` (default) | `live` |
| --- | --- | --- | --- |
| Embeddings | `EMBEDDING_PROVIDER` | Deterministic hash → unit-norm vector | Vertex AI `text-embedding-005` via `:predict` REST |
| Vector index | `VECTOR_SEARCH_PROVIDER` | In-memory cosine, namespace-isolated dict | Vertex AI Vector Search (`upsertDatapoints` + `findNeighbors`) |

`HeritageIndexer` ties the two adapters together: `index_documents([HeritageDoc])` embeds each doc, routes the upsert to that source's index using `doc.institution` as the namespace key, and packages period/region/category as Vertex AI `restricts` for filtered queries. `query(namespace, text)` searches one source; `query_all_sources(text)` fans out the same query vector across every configured namespace and merges the results — same fan-in + isolation contract as `MultiSourceHeritageAdapter`. Datapoint ids are `"{institution}:{external_id}"` so re-indexing the same source naturally upserts and cross-references with the heritage dedupe key line up exactly.

**Live mode wiring.** When `VECTOR_SEARCH_PROVIDER=live`, each namespace listed in `VERTEX_VECTOR_NAMESPACES` (default `jangseogak,koreanstudies,nlk,gihohak,nihc`) needs four env vars wired to the per-source Vertex resources:

```
VERTEX_VECTOR_INDEX_ID_<NAMESPACE>            # bare index resource id
VERTEX_VECTOR_DEPLOYED_INDEX_ID_<NAMESPACE>   # deployedIndexId on the endpoint
VERTEX_VECTOR_INDEX_ENDPOINT_ID_<NAMESPACE>   # IndexEndpoint resource id
VERTEX_VECTOR_INDEX_ENDPOINT_HOST_<NAMESPACE> # per-endpoint public domain
```

Vertex AI requires OAuth bearer tokens (not the `?key=...` query param that Gemini accepts), so live mode also needs `VERTEX_PROJECT_ID` plus a `GOOGLE_OAUTH_ACCESS_TOKEN` env var (production replaces this with a metadata-server token provider passed to `VertexAIEmbeddingAdapter` / `VertexAIVectorSearchAdapter`). Same graceful-degrade contract as the heritage / LLM layers: any missing piece (project id, token, or all per-namespace bundles) degrades the factory to `MockVectorSearchAdapter` with a warning so recipe-generate stays available while ops finishes provisioning. Both Vertex adapters call the REST surface directly with `httpx` to avoid pulling in the heavyweight `google-cloud-aiplatform` SDK — same pattern as the Gemini and Naver DataLab adapters.

### Trend discovery pipeline

The weekly trend dashboard (`/v1/trends`) is fed by one of three discovery modes, controlled by `TRENDS_DISCOVERY_SOURCE`:

| Mode | Sources | Use case |
| --- | --- | --- |
| `curated` (default) | Static watchlist of ≈79 K-heritage food keywords | Stable baseline, no external dependencies |
| `shopping_insight` | Naver DataLab Shopping Insight food category top-N | Production e-commerce signal |
| `open` | 4-source multi-provider fan-in (↓) | Open-domain discovery + novelty |

**`open` mode** combines four independent `TrendCandidateProvider`s and merges their output into the same blended-score ranking. Each provider runs in isolation — one failing does not break the refresh job:

| Provider | Toggle | Source | Notes |
| --- | --- | --- | --- |
| `static` | always on | Curated watchlist | Stable baseline keywords |
| `google_trends_daily` | `TRENDS_OPEN_GOOGLE_ENABLED` | Google Trends RSS (`trends.google.com/trending/rss?geo=KR`) | Stdlib XML, no SDK |
| `naver_news` | `TRENDS_OPEN_NAVER_NEWS_ENABLED` | Naver Search News compound-noun extraction (regex + per-article df) | Reuses `NAVER_DATALAB_CLIENT_ID/SECRET`; df cutoff via `NAVER_NEWS_MIN_ARTICLE_COUNT` (default 2) |
| `llm_expansion` | `TRENDS_OPEN_LLM_ENABLED` | Gemini 2.5 Flash JSON-schema response | Requires `GEMINI_API_KEY`; default off |

The food filter is **denylist-only** (`app/services/trends/food_filter.py`) — it rejects clearly non-food categories (정치/입법/법조/스포츠/연예/IT 제품/부동산/금융/거시지표/게임/의료/군사) but accepts everything else, including completely novel concepts (두바이쫀득쿠키, 마라탕후루, 트러플오일). This is intentional: PR #15 LLM expansion can then suggest Korean-heritage variants like 두바이강정 / 두바이약과.

For admin visibility, **`GET /v1/admin/trends/debug?today=YYYY-MM-DD&limit=N`** returns per-provider statistics (candidate count, sample of top-20 candidates, elapsed ms, error text if any) plus the merged ranked top-N with `all_sources` attribution per keyword. See `app/services/trends/debug.py`. The same payload is rendered in the admin UI at **`/admin/trends/debug`** (PR #22) — date picker for back-testing, limit selector, per-source cards with sample chips, and a merged-ranking table where each keyword shows every source that emitted it (primary source bolded). A one-shot "트렌드 스냅샷 즉시 갱신" button hooks into `POST /v1/admin/trends/refresh` so operators can re-run the pipeline without shelling into the box. Each ranked row also gets a 4-week mini sparkline (PR #23) fetched lazily from `/v1/trends/series` — the same data source that powers the dashboard's click-to-expand `TrendSeriesDialog`. Fan-out is capped at 30 keywords per page load so a `limit=100` admin view doesn't burst the Naver DataLab quota.

**Favorite keywords** (PR #24): authenticated users can star any trend keyword from the dashboard. The star toggle is wired to `POST /v1/private/me/favorite-keywords` (idempotent — re-starring an existing keyword is a no-op) and `DELETE /v1/private/me/favorite-keywords/{keyword}`. Stars are persisted in a new `user_favorite_keywords` table (one row per user × keyword, unique constraint enforced at the DB level). Starred keywords also show up in a "내 즐겨찾기 키워드" chip row at the top of the dashboard — clicking a chip opens the time-series dialog; clicking the X unstars. This table is the source of truth for the notification detector below and is intentionally distinct from `User.preferred_keywords` (set once during onboarding as a persona hint).

**In-app notifications** (PR #25): the `notifications` table records events surfaced to a single user (currently only `favorite_keyword_trending`). After every `refresh_trends` commit the `detect_favorite_keyword_notifications` service compares each user's favourites against this week's vs. last week's `trends` row and emits a notification row when (1) the keyword newly entered top-N, (2) its `change_percent >= 20%`, or (3) it jumped at least 5 ranks. Detection is per-`(user, keyword, week_of)` idempotent — re-running on the same week is a no-op. Notifications surface in a `<NotificationBell>` popover in the sidebar (unread badge on the bell, click an item to mark read, "모두 읽음" bulk action). The detector is wrapped in `try/except` inside the refresh job so a notification bug never rolls back the trend snapshot. Push / email channels are intentionally deferred — the model is channel-agnostic so adding them later is just a new dispatcher reading from the same table.

**Resilience**: when `TRENDS_DISCOVERY_SOURCE=open` is combined with `TRENDS_PROVIDER=live`, the merged candidate pool fans out to many Naver DataLab requests. The DataLab adapter (`naver.py`) catches per-chunk transport errors and 5xx upstream errors, logs a warning, and skips just the failed chunk — 401 auth / 429 quota errors still abort the whole refresh as expected.

**Naver News noise reduction** (PR #18): the `naver_news` provider applies two filters before ranking to keep the top-N free of generic news/marketing vocabulary. First, a per-article document-frequency cutoff (`NAVER_NEWS_MIN_ARTICLE_COUNT`, default 2) drops tokens that only appeared in a single article — a ranty article repeating one phrase no longer hijacks the trend list. Second, an explicit Korean stopword set strips news-prose residue (있다 / 더욱 / 오늘의), generic categories that match every seed query (디저트 / 카페 / 음료 / 신메뉴), and marketing meta-vocabulary (브랜드 / 트렌드 / 출시). Real food keywords like 아이스크림 / 커피 / 라떼 are *not* stopwords — they may be over-general but they are still legitimate signal.

**Google Trends denylist cleanup** (PR #20): the same `food_filter` is shared by `google_trends_daily`, `naver_news`, and `llm_expansion`, so denylist additions land everywhere at once. PR #20 covers concrete leak categories observed in live KR RSS (`가계부채`, `용인 FC 대 충남 아산 FC`, `mlb`): finance macro vocabulary (`GDP` / `실업률` / `예산안` / `경제성장률`), KBO/K-league teams + `FC` lookaround (UNICEF/PFC stay open), 정치 입법 (`법안` / `청문회`), 법조 (`검찰` / `탄핵` / `체포영장` / `소송`), 군사 (`전쟁` / `미사일` / `드론`), 영화제/시사회. The regex compiles with `re.IGNORECASE` so lowercase RSS variants (`mlb` / `fc` / `gdp`) match alongside uppercase forms.

**Bare proper-name denylist** (PR #26): the remaining limitation from PR #20 — bare Korean names like `홍상수` / `손흥민` / `김상식` and foreign transliterations like `짜라위` — is closed for ~60 frequently-leaked names tracked in `_BARE_PERSON_NAME_DENYLIST`. Only 3+ syllable names are included to avoid surname-syllable collisions with food vocabulary (`홍어` / `박하사탕` / `이밥` / `김치찌개` still pass; common Korean surname-only tokens are intentionally not on the list). 먹방 YouTubers are intentionally excluded because they belong in food trends. New leaks are added by appending to the tuple — downstream blended scoring + Gemini expansion remain the primary safety net, so the list is belt-and-suspenders rather than the single source of truth.

**Broader macro / brand denylist** (PR #27): extends the same `food_filter` with five more categories that were observed leaking in live KR RSS — 정부 지출 (`교부금` / `보조금` / `지원금` / `재난지원금`), 세제 / 무역 (`무역수지` / `경상수지` / `수출액` / `관세인상` / `부가가치세` / `법인세` / `종부세`), 외국 자동차 브랜드 + 모델 (`테슬라` / `벤츠` / `BMW` / `사이버트럭` / `모델Y`…), 암호화폐 / 가상자산 (`비트코인` / `이더리움` / `업비트` / `NFT`…), and 항공우주 (`누리호` / `다누리` / `SpaceX` / `로켓발사`). The deliberate exclusions are just as important: bare `수출` would block legitimate food trends like `김치 수출` / `한국 농산물 수출`; bare `로켓` would block `로켓샐러드` (rocket leaves); bare `애플` would block `애플파이` / `애플망고`; bare `인스타` / `틱톡` / `유튜브` would block real food-on-social trends. We keep those out and rely on collision-safe compound forms (`수출액` / `로켓발사` / `애플워치` if added later). 100 새 테스트 가 reject 동작 + collision-safety 양쪽을 잠금.

**Geographic / industry / 예능 / news-prose cleanup** (PR #28): closes four leak families that surfaced in the most recent live snapshot. (1) Bare country names anchored with `^…$` (`홍콩` / `대만` / `미국` / `일본` / `중국` / `프랑스`…) — compound forms like `홍콩식 디저트` still pass because the anchor only matches the bare token. (2) Bare industry / lifestyle categories (`뷰티` / `패션` / `명품` / `버킨백` / `게임` / `가전`) that were leaking from Shopping Insight cross-vertical feeds. (3) Korean variety / 예능 program names (`편스토랑` / `런닝맨` / `놀면 뭐하니`…) that the news provider picked up around tie-in product launches. (4) An extension of the PR #26 bare-name list (`박형룡` and ~10 other transliterated foreign names) plus a small news-prose stopword extension (`밝혔다` / `전했다`-style verb forms surfacing as standalone tokens from naver_news). 411 백엔드 테스트 그린 + 7 회귀 케이스 신규 추가.

### Production rollout (PR #19)

To switch the dashboard from the static curated baseline to the full live multi-source pipeline, set the following in `apps/api/.env` (or your deployment's secret manager):

```env
TRENDS_DISCOVERY_SOURCE=open
TRENDS_PROVIDER=live
NAVER_DATALAB_CLIENT_ID=...        # same app as Shopping Insight + News
NAVER_DATALAB_CLIENT_SECRET=...
TRENDS_OPEN_LLM_ENABLED=true       # optional; daily ~$0.01 in Gemini cost
GEMINI_API_KEY=...
TRENDS_REFRESH_HOUR_UTC=18         # 18 UTC = 03 KST; new top-N ready by morning
```

**Log redaction** (PR #29): `gemini_trends.py` installs a process-wide `httpx` log filter (`_httpx_log_redact.py`) on first use that rewrites `?key=…` query params to `?key=REDACTED` before they hit any handler. This applies to both string-formatted URLs and `httpx.URL` arg-record forms, is idempotent, and covers the `generativelanguage.googleapis.com` host that exposes the Gemini key in the URL itself. With this in place, raw `AIzaSy…` strings never appear in stdout / journald / log shipping — even at httpx `INFO` level. No action needed by operators; the filter is installed automatically when the Gemini provider is constructed.

`docker compose up` will then bring up an additional **`trends_refresher`** sidecar that runs `python -m app.jobs.refresh_scheduler`. The scheduler is a minimal stdlib loop — it sleeps in 60-second chunks until the next scheduled hour and runs `refresh_trends` once per day. Each iteration's refresh is wrapped in try/except so one bad day (Gemini outage, Naver quota) does not crash the loop. Operators with their own scheduler (Kubernetes `CronJob`, host cron, GitHub Actions schedule, AWS EventBridge) can drop the `trends_refresher` service and invoke `python -m app.jobs.refresh_trends` directly on their preferred cadence.

The admin endpoint `POST /v1/admin/trends/refresh` remains available for on-demand refresh; `GET /v1/admin/trends/debug` continues to show per-provider statistics for live verification.

## API surface (selected)

| Method | Path                                         | Auth   | Description                       |
| ------ | -------------------------------------------- | ------ | --------------------------------- |
| POST   | `/v1/auth/register`                          | -      | Create account, returns JWTs      |
| POST   | `/v1/auth/login`                             | -      | Email + password → JWTs           |
| POST   | `/v1/auth/refresh`                           | -      | Exchange refresh token            |
| GET    | `/v1/auth/me`                                | user   | Current user + plan               |
| GET    | `/v1/trends`                                 | -      | Weekly trend keywords             |
| POST   | `/v1/admin/trends/refresh`                   | admin  | Re-run discovery + score          |
| GET    | `/v1/admin/trends/debug`                     | admin  | Per-source breakdown + diagnostics |
| GET    | `/v1/documents`                              | -      | Search heritage documents         |
| POST   | `/v1/private/recipes/generate`               | user   | AI generates 3 candidates         |
| GET    | `/v1/private/recipes`                        | user   | My saved recipes                  |
| GET    | `/v1/private/recipes/{id}`                   | user   | Recipe detail                     |
| GET    | `/v1/private/recipes/{id}/export/pdf`        | user   | PDF (watermarked for free plan)   |
| GET    | `/v1/private/recipes/{id}/certificate`       | Pro+   | Heritage attestation              |
| GET    | `/v1/private/me/favorite-keywords`           | user   | List starred trend keywords       |
| POST   | `/v1/private/me/favorite-keywords`           | user   | Star a keyword (idempotent)       |
| DELETE | `/v1/private/me/favorite-keywords/{keyword}` | user   | Unstar a keyword                  |
| GET    | `/v1/private/me/notifications`               | user   | List notifications + unread count |
| POST   | `/v1/private/me/notifications/{id}/read`     | user   | Mark a notification read          |
| POST   | `/v1/private/me/notifications/read-all`      | user   | Mark all notifications read       |
| POST   | `/v1/payments/billing/confirm`               | user   | Save Toss billing key             |
| GET    | `/v1/admin/recipes`                          | admin  | Review queue                      |
| POST   | `/v1/admin/recipes/{id}/status`              | admin  | Approve / reject / flag           |

Full OpenAPI spec at `/v1/openapi.json`.

## Tech spec compliance

This MVP implements the functional requirements from `k-heritage-recipe-ai-tech-spec-v1_4`:

- **FR-01** authentication (JWT + refresh) — done (Google OAuth stub TBD)
- **FR-02** weekly trend dashboard — done
- **FR-03** AI recipe generation (3 candidates from public-API context) — done via mock pipeline
- **FR-04** heritage document search — done
- **FR-05** PDF export — done
- **FR-06** heritage attestation certificate (Pro/B2B) — done
- **FR-07** review-queue (human-in-the-loop) — done
- **NFR-09** mocked external services for offline / CI runs — done
- **Section 8.2** admin pages — backend done, frontend basic page

Items deferred until live keys are provided: real Gemini calls, real public-API crawlers, TossPayments sandbox, Vertex AI Vector Search live indices (mock + Vertex REST adapters are wired), GCP Cloud Run deploy.

## License

MIT
