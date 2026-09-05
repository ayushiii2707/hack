# Checkout Copilot

A conversational AI shopping & checkout agent embedded in a merchant app. The
customer talks naturally to build a cart and pays with **real Razorpay
Test-Mode APIs** — while a deterministic backend stays the sole authority for
identity, pricing, stock, checkout and payments.

> Core rule: **the LLM is never the source of truth.** It orchestrates
> conversation and picks among a small set of allow-listed tools. Every commerce
> fact, every limit, and every payment transition is enforced in backend code
> and, where integrity demands it, by database constraints.

---

## Architecture

```
                 ┌───────────────┐
                 │   React UI    │  (Vite + TS) — displays; never computes totals
                 └──────┬────────┘   sends `Authorization: Bearer <session token>`
                        ▼
     CORS · TrustedHost · request-id · per-IP rate limit
                        ▼
                 ┌───────────────┐
                 │   FastAPI     │  auth + ownership on every stateful route
                 └──────┬────────┘
             ┌──────────┴───────────┐
             ▼                      ▼
   ┌───────────────────┐   ┌──────────────────┐
   │  Agent (LangChain │   │  Session-scoped  │
   │   + Gemini)       │   │  REST endpoints  │
   └────────┬──────────┘   └────────┬─────────┘
     typed args → PolicyEngine → Service ──────┘
                       ▼
              ┌──────────────────┐
              │  Service layer   │  invariants, state machines, atomic ops
              └────────┬─────────┘
             ┌──────────┴───────────┐
             ▼                      ▼
     ┌───────────────┐     ┌──────────────────┐
     │ Repositories  │     │ Integrations     │  DummyJSON · Razorpay · Gemini
     └───────┬───────┘     └──────────────────┘
             ▼
   PostgreSQL (prod) / SQLite (dev)   — CHECK + UNIQUE constraints, Alembic
```

### Security model

* **Identity:** anonymous sessions. `POST /sessions` issues an opaque bearer
  token; only a **peppered hash** of it is stored (`SESSION_TOKEN_SECRET`). No
  accounts, no passwords. Every `/cart`, `/checkout`, `/upsell`, `/payments`,
  `/agent`, `/audit` call is scoped to the token's session — there are **no
  guessable path ids to attack**.
* **Payments:** the amount always comes from the internal `Order`. An order
  reaches `PAID` **only** after the Razorpay signature verifies **and** an
  independent gateway fetch confirms `status` + `amount` + `currency` +
  `order_id`. Webhooks are signature-required (the app refuses to start in
  production without `RAZORPAY_WEBHOOK_SECRET`), amount-checked, and deduped by
  provider event id in the database.
* **Concurrency:** the one-shot upsell, "one open order per cart", and stock
  reservation are enforced by **atomic guarded `UPDATE`s / `UNIQUE` columns**,
  not check-then-act — proven by threaded tests.
* **Agent:** 12 allow-listed tools, none of which can run SQL, reach the
  database or Razorpay directly, execute a payment, or drive the session state
  machine. Every tool is typed args → policy → service. Prompt injection is
  covered by regression tests.
* **Abuse:** per-IP token-bucket rate limits on `/agent/chat`, `/payments/*`,
  `/sessions`, `/webhooks`, search. Configurable.
* **Ops:** `X-Request-ID` on every request + audit row; structured JSON logs
  (`LOG_JSON=true`); `/health` + `/health/ready`; Alembic migrations; Dockerfile
  (non-root, healthcheck) + `docker-compose.yml` (Postgres); GitHub Actions CI
  (lint + `alembic check` + tests + `npm audit` + build).

---

## Features

- Conversational discovery, cart building, one explainable upsell, checkout,
  real Razorpay Test-Mode payment, deliberate failure → retry / payment-link
  recovery, full audit trail.
- **No forced account creation.** **Full price shown before payment.**
- Stock is **atomically reserved** at checkout (no overselling); released on
  cancel.

### Deliberate V1 scope boundaries

- The catalog is a **mock set** ingested from DummyJSON, not a live merchant
  inventory. A local product's stock becomes authoritative once reserved; sync
  no longer clobbers it.
- The upsell model is a **simple, explainable weighted score**, not a
  production recommender.

---

## Setup — local (SQLite)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # dev works out of the box; fill keys for the full demo
python -m app.database.seed     # migrate + sync catalog
uvicorn app.main:app --reload   # http://localhost:8000  (docs at /docs)
```

```bash
cd frontend
npm install
cp .env.example .env            # VITE_API_BASE=/api uses the dev proxy
npm run dev                     # http://localhost:5173
```

## Setup — production-shaped (Docker + Postgres)

```bash
cp backend/.env.example backend/.env   # set SESSION_TOKEN_SECRET, Razorpay keys,
                                       # ENVIRONMENT=production, TRUSTED_HOSTS, CORS_ORIGINS
docker compose up --build              # frontend :8080, backend :8000, postgres
```
The backend container runs `alembic upgrade head` on start and refuses to boot
if the config is unsafe for `ENVIRONMENT=production` (see
`Settings.validate_for_environment`).

---

## Environment variables

Every variable is documented inline in [`backend/.env.example`](backend/.env.example).
The security-critical ones:

| Variable | Meaning |
|----------|---------|
| `SESSION_TOKEN_SECRET` | HMAC pepper for session-token hashes. **Required (≥32 chars) in production.** |
| `RAZORPAY_KEY_ID` / `_SECRET` | Test-Mode keys (`rzp_test_…`). |
| `RAZORPAY_WEBHOOK_SECRET` | **Required once Razorpay keys are set.** Unsigned webhooks are rejected. |
| `ADMIN_API_KEY` | Enables `/audit/admin` + `/products/sync`. Blank = those endpoints disabled. |
| `ENABLE_DEMO_ENDPOINTS` | `/payments/simulate-failure`. **Must be false in production.** |
| `GEMINI_API_KEY` | Optional — a deterministic keyword router (same tools/policies) runs without it. |
| `DATABASE_URL` | `sqlite:///…` for dev; `postgresql+psycopg://…` for production. |
| `TRUSTED_HOSTS`, `CORS_ORIGINS` | Must be explicit lists in production. |
| `SESSION_COOKIE_SECURE` | Must be `true` behind HTTPS. |
| `RATE_LIMIT_*` | Per-IP limits (requests/minute) per endpoint class. |

### Razorpay Test Mode

1. Razorpay dashboard → **Test Mode** → Settings → API Keys → generate.
2. Settings → Webhooks → add `https://<host>/webhooks/razorpay`, set a secret
   (→ `RAZORPAY_WEBHOOK_SECRET`), subscribe to `payment.captured`,
   `payment.failed`, `order.paid`.
3. Test card for success: `4111 1111 1111 1111`, any future expiry / CVV. For a
   failure choose **Failure** on Razorpay's test page, or use the app's
   `Demo: force failure` button (non-prod only).

---

## Tests

```bash
cd backend && pytest            # 166 tests
cd backend && ruff check .
cd frontend && npm run build
```

Coverage includes: **no cross-session access** (auth/IDOR), **forged webhook
rejected / fails closed without a secret**, **signature-valid-but-wrong-amount
rejected**, **one-shot upsell holds under 16 concurrent requests**, **concurrent
checkout confirm creates exactly one order**, **10 buyers racing for 3 units →
exactly 3 succeed**, terminal payment attempts are immutable, duplicate webhook
event ids are ignored, prompt injection cannot bypass any control, and a full
`session → search → cart → upsell → decline → confirm → fail → retry → PAID →
audit` end-to-end flow (`tests/test_e2e.py`).

---

## Demo

See [`DEMO.md`](DEMO.md).
