---
name: local-dev
description: Run, seed, lint and test the K-Heritage Recipe AI stack locally. Covers Vite proxy gotcha and the demo-account login bug. Use whenever you need to bring the full stack up for manual or browser testing.
---

# Local dev — K-Heritage Recipe AI

## One-shot setup
```bash
# Backend (FastAPI) — first time only
cd apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]" 'bcrypt<4.1'   # pin bcrypt: passlib breaks on >=4.1

# Frontend (Vite + React)
cd apps/web && npm install
```

## Run the stack
```bash
# tab 1 — API on :8000
cd apps/api && . .venv/bin/activate
export JWT_SECRET_KEY=local-dev-secret-key-must-be-long
export LLM_PROVIDER=mock HERITAGE_PROVIDER=mock PAYMENTS_PROVIDER=mock
export CORS_ALLOW_ORIGINS=http://localhost:5173
python -m app.db.seed     # idempotent — creates demo + admin + trends + documents
uvicorn app.main:app --port 8000 --reload

# tab 2 — web on :5173
cd apps/web && npm run dev   # DO NOT set VITE_API_URL (see gotcha below)
```

## Gotchas

### 1. `VITE_API_URL` must NOT include `/v1`
`apps/web/vite.config.ts` proxies `/v1/*` to `${VITE_API_URL || 'http://localhost:8000'}`. The api client (`src/lib/api.ts`) already prefixes paths with `/v1`. If you export `VITE_API_URL=http://localhost:8000/v1` every request becomes `/v1/v1/...` → 404. Either leave the env var unset (recommended) or use `VITE_API_URL=http://localhost:8000`.

### 2. Demo / admin accounts cannot log in via the API
`pydantic.EmailStr` (email-validator) rejects the reserved `.local` TLD. The seeded users `demo@k-heritage.local` and `admin@k-heritage.local` exist in the DB (inserted via ORM, bypassing schema validation) but `/v1/auth/login` returns **422** for them:
```
value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.
```
For any UI testing that needs an authenticated user, **register a fresh `@gmail.com` (or other non-reserved) account** instead of trying to log in as demo/admin. Same applies to register: don't try `.local` emails.

## Commands

### Lint / format / typecheck
```bash
# backend
cd apps/api && . .venv/bin/activate
ruff check . && ruff format --check .

# frontend
cd apps/web
npx tsc --noEmit
```

### Tests
```bash
# backend (pytest, sqlite in-memory)
cd apps/api && . .venv/bin/activate && pytest -q

# frontend has no unit tests yet
```

### Build (sanity check before pushing)
```bash
cd apps/web && npm run build
```

## Useful endpoints
- `GET  /v1/auth/me`               — current user (incl. `onboarding_completed`, `persona`, `preferred_regions`, `preferred_keywords`)
- `POST /v1/auth/register`         — JSON `{email, password, display_name}` → tokens
- `POST /v1/auth/login`            — JSON `{email, password}` → tokens
- `POST /v1/auth/refresh`          — JSON `{refresh_token}` → new tokens
- `PATCH /v1/private/users/me`     — partial profile update (onboarding writes here)
- `GET  /v1/trends?region=전국`     — trend keywords (used by onboarding page chips)
- API docs: <http://localhost:8000/docs>

## Frontend routes (auth-gated)
All routes except `/login` and `/onboarding` go through `ProtectedRoute`. If `user.onboarding_completed === false`, any protected nav bounces to `/onboarding`. The `/onboarding` route itself uses `requireOnboarding={false}` so it doesn't loop.
