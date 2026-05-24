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
| LLM       | `LLM_PROVIDER`       | Deterministic 3 candidates    | Gemini 2.5 Pro (requires `GEMINI_API_KEY`)   |
| Trends    | `TRENDS_PROVIDER`    | Deterministic ratios          | Naver DataLab (`NAVER_DATALAB_CLIENT_ID/SECRET`) |
| Heritage  | `HERITAGE_PROVIDER`  | 3 seed documents (음식디미방 etc.) | 장서각 / 국립민속박물관 / 문화데이터광장 (keys required) |
| Payments  | `PAYMENTS_PROVIDER`  | Always succeeds, fake billing | TossPayments (`TOSS_SECRET_KEY` required)    |

Live adapters for LLM / heritage / payments are scaffolded but raise `NotImplementedError` until wired — switching is a single env var change once keys are provided. The trends adapter is fully wired live.

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

For admin visibility, **`GET /v1/admin/trends/debug?today=YYYY-MM-DD&limit=N`** returns per-provider statistics (candidate count, sample of top-20 candidates, elapsed ms, error text if any) plus the merged ranked top-N with `all_sources` attribution per keyword. See `app/services/trends/debug.py`. The same payload is rendered in the admin UI at **`/admin/trends/debug`** (PR #22) — date picker for back-testing, limit selector, per-source cards with sample chips, and a merged-ranking table where each keyword shows every source that emitted it (primary source bolded). A one-shot "트렌드 스냅샷 즉시 갱신" button hooks into `POST /v1/admin/trends/refresh` so operators can re-run the pipeline without shelling into the box.

**Resilience**: when `TRENDS_DISCOVERY_SOURCE=open` is combined with `TRENDS_PROVIDER=live`, the merged candidate pool fans out to many Naver DataLab requests. The DataLab adapter (`naver.py`) catches per-chunk transport errors and 5xx upstream errors, logs a warning, and skips just the failed chunk — 401 auth / 429 quota errors still abort the whole refresh as expected.

**Naver News noise reduction** (PR #18): the `naver_news` provider applies two filters before ranking to keep the top-N free of generic news/marketing vocabulary. First, a per-article document-frequency cutoff (`NAVER_NEWS_MIN_ARTICLE_COUNT`, default 2) drops tokens that only appeared in a single article — a ranty article repeating one phrase no longer hijacks the trend list. Second, an explicit Korean stopword set strips news-prose residue (있다 / 더욱 / 오늘의), generic categories that match every seed query (디저트 / 카페 / 음료 / 신메뉴), and marketing meta-vocabulary (브랜드 / 트렌드 / 출시). Real food keywords like 아이스크림 / 커피 / 라떼 are *not* stopwords — they may be over-general but they are still legitimate signal.

**Google Trends denylist cleanup** (PR #20): the same `food_filter` is shared by `google_trends_daily`, `naver_news`, and `llm_expansion`, so denylist additions land everywhere at once. PR #20 covers concrete leak categories observed in live KR RSS (`가계부채`, `용인 FC 대 충남 아산 FC`, `mlb`): finance macro vocabulary (`GDP` / `실업률` / `예산안` / `경제성장률`), KBO/K-league teams + `FC` lookaround (UNICEF/PFC stay open), 정치 입법 (`법안` / `청문회`), 법조 (`검찰` / `탄핵` / `체포영장` / `소송`), 군사 (`전쟁` / `미사일` / `드론`), 영화제/시사회. The regex compiles with `re.IGNORECASE` so lowercase RSS variants (`mlb` / `fc` / `gdp`) match alongside uppercase forms. Known limitation: bare Korean person names (`홍상수`, `손흥민`) and foreign transliterations (`짜라위 분짠`) still pass through — see the docstring in `food_filter.py` for the rationale and follow-up plan.

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

Items deferred until live keys are provided: real Gemini calls, real public-API crawlers, TossPayments sandbox, Vertex AI Vector Search, GCP Cloud Run deploy.

## License

MIT
