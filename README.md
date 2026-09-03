# Checkout Copilot

A conversational AI shopping & checkout agent embedded in a demo merchant app.
The customer talks naturally to build a cart and pay with **real Razorpay
Test-Mode APIs** — while a deterministic backend stays the sole authority for
pricing, checkout, upsell limits and payments.

> The single most important design rule: **the LLM is never the source of truth.**
> It orchestrates conversation and picks among a small set of allow-listed
> tools. Every commerce fact and every hard limit is enforced in backend code.

---

## Architecture

```
                 ┌───────────────┐
                 │   React UI    │  (Vite + TS) — displays, never computes totals
                 └──────┬────────┘
                        │  POST /agent/chat, REST
                 ┌──────▼────────┐
                 │   FastAPI     │  API layer — request/response only
                 └──────┬────────┘
             ┌──────────┴───────────┐
             ▼                      ▼
   ┌───────────────────┐   ┌──────────────────┐
   │  Agent (LangChain │   │  Direct REST     │
   │   + Gemini)       │   │  cart/checkout/… │
   └────────┬──────────┘   └────────┬─────────┘
            ▼ constrained tools     │
   ┌───────────────────┐            │
   │  Policy engine    │  2nd line of defence (POLICY_BLOCKED audit)
   └────────┬──────────┘            │
            └──────────┬────────────┘
                       ▼
              ┌──────────────────┐
              │  Service layer   │  commerce logic + invariants
              └────────┬─────────┘
             ┌──────────┴───────────┐
             ▼                      ▼
     ┌───────────────┐     ┌──────────────────┐
     │ Repositories  │     │ Integrations     │
     │ (SQLAlchemy)  │     │ DummyJSON /      │
     └───────┬───────┘     │ Razorpay / Gemini│
             ▼             └──────────────────┘
     ┌───────────────┐
     │ SQLite (V1)   │  runtime source of truth
     └───────────────┘
```

Layer responsibilities:

| Layer        | Responsibility |
|--------------|----------------|
| API          | HTTP request/response, schema validation |
| Agent        | natural-language orchestration, tool selection |
| Policy       | permission / boundary enforcement (2nd line) |
| Service      | business logic, invariants, state machines |
| Repository   | persistence only, no business rules |
| Integration  | external APIs (DummyJSON, Razorpay, Gemini) |
| Model        | database representation |
| Schema       | API / tool input & output validation |

### What the LLM may and may **not** do

| Allowed (via tools)                        | Never (enforced in backend)                |
|--------------------------------------------|--------------------------------------------|
| understand NL, choose an allowed tool      | calculate authoritative price / total      |
| `search_products`, `get_product`           | invent products / stock / prices           |
| `add_to_cart` / `update_cart_quantity` / `remove_from_cart` | exceed `MAX_ITEM_QUANTITY` |
| `get_cart`, `calculate_total`              | modify DB rows / order totals directly     |
| `request_upsell` (once per session)        | show a 2nd upsell / re-prompt after decline |
| `start_checkout` (shows total, no payment) | execute payment / mark an order paid       |
| `get_checkout_status`                      | call Razorpay directly                     |

There is **no** `pay()` / `execute_payment` / `raw_sql` / `raw_razorpay` tool.

---

## Features

- Conversational product discovery (natural language → internal DB search)
- Cart management by chat or by clicking — quantity cap + stock enforced server-side
- Authoritative price breakdown (integer **paise**, deterministic shipping rule)
- **Exactly one** explainable upsell per session, price-capped, never repeated
- Checkout review that shows the **full price incl. fees before** any payment
- **No forced account creation** — a session id is the only identity
- Real Razorpay **Test Mode** Orders + Payment Links + signature verification
- Deliberate payment failure → retry → payment-link fallback, all persisted
- Append-only audit trail with a plain-language reason on every business action
- Idempotent checkout confirm, payment verify and webhook handling

### Deliberate scope boundaries (say this in the pitch)

- The catalog is a **mock set** ingested from DummyJSON, not a live merchant inventory.
- The upsell model is a **simple, explainable weighted score**, not a production recommender.

Both are intentional choices for the time box, not hidden gaps.

---

## Tech stack

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, SQLite, Pydantic v2 / pydantic-settings,
httpx, LangChain (`create_agent`) + `langchain-google-genai` (Gemini), `razorpay`, pytest.

**Frontend:** React 18, Vite, TypeScript, plain CSS. Talks only to the backend API.

---

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the keys (see below)
python -m app.database.seed   # create tables + sync catalog from DummyJSON
uvicorn app.main:app --reload # http://localhost:8000  (docs at /docs)
```

`python -m app.database.seed` is idempotent: it creates tables, pulls the catalog
into SQLite, and verifies products exist. Re-run any time to refresh the catalog
(`python -m app.integrations.catalog.sync` does just the sync).

> Run the seed **before** starting `uvicorn`. Don't recreate the DB file while the
> server is running.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env          # VITE_API_BASE=/api uses the dev proxy to :8000
npm run dev                   # http://localhost:5173
```

---

## Environment variables (`backend/.env`)

| Variable | Meaning |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy URL. Default `sqlite:///./checkout_copilot.db`. |
| `GEMINI_API_KEY` | Google AI Studio key. If empty, a deterministic keyword-router fallback agent is used (same tools/policies) so the demo still runs. |
| `GEMINI_MODEL` | Default `gemini-2.0-flash`. |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | **Test Mode** keys (`rzp_test_…`) from Razorpay Dashboard → Settings → API Keys. |
| `RAZORPAY_WEBHOOK_SECRET` | Secret you set when creating the webhook; used to verify `POST /webhooks/razorpay`. |
| `CATALOG_BASE_URL` | External catalog provider. Default `https://dummyjson.com`. |
| `CATALOG_SYNC_LIMIT` | How many products to ingest (194 = all of DummyJSON). |
| `CATALOG_PRICE_MULTIPLIER` | DummyJSON prices are small USD floats; `35` turns them into realistic INR. |
| `MAX_ITEM_QUANTITY` | Per-product cap. Default `5`. Breach → `POLICY_BLOCKED` audit + 403. |
| `UPSELL_PRICE_CAP_PERCENT` | Upsell must be ≤ this % of the cart subtotal. Default `20`. |
| `SHIPPING_FEE` | Flat shipping in **paise**. Default `500` (₹5). |
| `FREE_SHIPPING_THRESHOLD` | Subtotal in **paise** at/above which shipping is free. Default `200000` (₹2,000). |

Money-shaped values are integer **paise** everywhere in the backend. The frontend
only formats for display.

### Razorpay Test Mode

1. Create a Razorpay account, switch the dashboard to **Test Mode**.
2. Settings → API Keys → **Generate Test Key**. Put the id/secret in `.env`.
3. (Optional, for webhooks) Settings → Webhooks → add `https://<tunnel>/webhooks/razorpay`,
   set a secret, subscribe to `payment.captured`, `payment.failed`, `order.paid`.
   Put the secret in `RAZORPAY_WEBHOOK_SECRET`.
4. Test card for success: `4111 1111 1111 1111`, any future expiry, any CVV, any name.
   To simulate a **failure**, choose **Failure** on Razorpay's test payment page, or
   use the app's `Demo: force failure` button (deterministic, non-prod only).

### Gemini

Get a key at <https://aistudio.google.com/app/apikey> → `GEMINI_API_KEY`.
Without it the app transparently uses a small deterministic intent router that
calls the exact same tools and policies (search / cart / upsell / checkout).

---

## Running the tests

```bash
cd backend && pytest            # 75 tests
```

Coverage includes every hard boundary: quantity `999999` blocked + audited, no
payment tool exists, second upsell blocked, declined-then-retry blocked, and a
frontend "payment succeeded" claim without a valid signature is **not** marked
paid. Plus catalog sync idempotency, price snapshots, pricing in paise, checkout
state machine, Razorpay order/verify/retry/link, and duplicate-webhook safety.

---

## Demo flow

See [`DEMO.md`](DEMO.md) for the full script. In short:

1. "Show me running shoes under ₹3000" → agent searches the internal DB.
2. "Add the first one" (or click **Add to cart**).
3. "Show me my cart" → authoritative subtotal / shipping / total.
4. **Review & Checkout** → full price shown before anything is charged.
5. Exactly one upsell appears, with a concrete reason and a price cap.
6. Decline it → recorded as `UPSELL_DECLINED`, never asked again.
7. **Proceed to Payment** → backend creates a real Razorpay Test-Mode order.
8. Pay with the failure option → `PAYMENT_FAILED` recorded, order **not** paid.
9. **Retry payment** with `4111 1111 1111 1111` → `PAYMENT_SUCCESS`, order `PAID`,
   session `COMPLETED`. (Or **Get payment link** for the Razorpay Payment Link fallback.)
10. Open **Audit trail** to show every step with its plain-language reason.

---

## Project layout

```
backend/app/
  core/         config, constants (enums + state-transition whitelist), exceptions, security
  api/          health, sessions, products, cart, checkout, upsell, payments, webhooks, agent, audit
  agent/        agent.py, prompts, state, tools, tool_schemas, policies
  services/     session, product, cart, pricing, checkout, upsell, payment, audit
  models/       product, session, cart, cart_item, order, payment, audit_log
  schemas/      pydantic request/response models
  repositories/ persistence only
  integrations/ catalog/{base,dummyjson,normalizer,sync}, razorpay/{client,orders,payments,payment_links}, llm/gemini
  database/     database.py, seed.py
  utils/        money (paise), ids, time, logging
backend/tests/  test_products, test_cart, test_pricing, test_upsell, test_checkout,
                test_payments, test_policies, test_agent, test_agent_fallback, test_money, test_health
frontend/src/   App.tsx, lib/{api,razorpay}, components/{ChatPanel,ProductGrid,CartPanel,UpsellCard,CheckoutModal,AuditDrawer}
```
