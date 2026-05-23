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
| Heritage  | `HERITAGE_PROVIDER`  | 3 seed documents (음식디미방 etc.) | 장서각 / 국립민속박물관 / 문화데이터광장 (keys required) |
| Payments  | `PAYMENTS_PROVIDER`  | Always succeeds, fake billing | TossPayments (`TOSS_SECRET_KEY` required)    |

Live adapters are scaffolded but raise `NotImplementedError` until wired — switching is a single env var change once keys are provided.

## API surface (selected)

| Method | Path                                         | Auth   | Description                       |
| ------ | -------------------------------------------- | ------ | --------------------------------- |
| POST   | `/v1/auth/register`                          | -      | Create account, returns JWTs      |
| POST   | `/v1/auth/login`                             | -      | Email + password → JWTs           |
| POST   | `/v1/auth/refresh`                           | -      | Exchange refresh token            |
| GET    | `/v1/auth/me`                                | user   | Current user + plan               |
| GET    | `/v1/trends`                                 | -      | Weekly trend keywords             |
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
