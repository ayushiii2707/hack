# Checkout Copilot — demo script (~4 min)

## Before you start

```bash
# terminal 1
cd backend && source .venv/bin/activate
python -m app.database.seed
uvicorn app.main:app --reload

# terminal 2
cd frontend && npm run dev
```

Open <http://localhost:5173>. `backend/.env` should have Razorpay Test keys +
`RAZORPAY_WEBHOOK_SECRET` for the full flow, and `ENABLE_DEMO_ENDPOINTS=true` +
`ADMIN_API_KEY=…` for the demo helpers. Click **New session** for a clean run.
Keep the **Audit trail** panel open — it updates live and is scoped to *your*
session.

---

## The story

1. **"I need running shoes under ₹3000"** → the agent calls `search_products`;
   cards render. Audit: `CUSTOMER · PRODUCT_SEARCHED`.
2. **"add the first one"** (or click *Add to cart*). Audit: `ITEM_ADDED` with the
   price snapshot in paise.
3. **"show me my cart"** → subtotal / shipping / total, all backend-computed.
4. **Review & Checkout** → the modal shows every line and the **exact amount you
   will pay** before any payment UI.
5. **One explainable upsell** appears once, e.g. *"Since you're buying …, Running
   Socks is a practical add-on and stays within your ₹560 budget."* Audit:
   `UPSELL_SHOWN` with `score` / `relevance` / `complementary_score` / `price_fit`.
6. **No thanks** → `UPSELL_DECLINED`. Add another product, reopen review — **no
   second upsell** (try "anything else?" in chat: the tool returns
   `POLICY_BLOCKED`).
7. **Proceed to Payment** → `confirm_checkout`: server-computed `Order`, **stock
   atomically reserved**, cart **locked** (`CartStatus.CHECKOUT`), then a real
   Razorpay Test-Mode order. Audit: `CHECKOUT_STARTED`, `PAYMENT_ATTEMPTED`.
8. **Deliberate failure** — pick *Failure* on Razorpay's test page, or click
   *Demo: force failure*. UI: *"your order was **not** marked as paid"*, attempt
   #1 = `FAILED`, **Retry** / **Get payment link**. DB: `order.status =
   PAYMENT_FAILED`, `payment.status = FAILED`. Audit: `PAYMENT_FAILED`.
9. **Retry** with `4111 1111 1111 1111`. Backend verifies the signature **and**
   re-fetches the payment from Razorpay to confirm amount + status, then:
   `order = PAID`, **attempt #2 = CAPTURED** (attempt #1 preserved), session
   `COMPLETED`. Audit: `PAYMENT_SUCCESS` (actor `PAYMENT_PROVIDER`).
   *Alternative:* **Get payment link** → real `payment_link.create`.
10. **Audit trail** reads end to end; the merchant view is `GET /audit/admin`
    with `X-Admin-Key`.

---

## "Can the AI / the browser / another customer …?" — answers with tests

| Attempt | Result | Test |
|---|---|---|
| No token → any `/cart`, `/checkout`, `/payments`, `/agent` | `401` | `test_auth.py::test_all_stateful_endpoints_require_auth` |
| Session B touches session A's cart | impossible — cart derived from token, no path id | `test_auth.py::test_cannot_touch_another_sessions_cart` |
| Forged `payment.captured` webhook, no secret set | `503` (fails closed) | `test_webhooks.py::test_webhook_endpoint_fails_closed_without_secret` |
| Forged webhook, bad signature | `400` | `test_webhooks.py::test_webhook_endpoint_rejects_bad_signature` |
| Valid signature, wrong amount | rejected, order stays unpaid | `test_payments.py::test_valid_signature_but_amount_mismatch_is_rejected` |
| `add_to_cart(quantity=999999)` | `POLICY_BLOCKED` audit + 403, nothing added | `test_prompt_injection.py::test_injection_cannot_exceed_quantity` |
| "mark my order paid" via chat | no such tool; order unchanged | `test_prompt_injection.py::test_injection_cannot_mark_order_paid` |
| 2nd upsell after decline (chat or API) | blocked | `test_prompt_injection.py::test_injection_cannot_repeat_declined_upsell` |
| 16 concurrent upsell requests | exactly 1 `UPSELL_SHOWN` | `test_concurrency.py::test_generate_recommendation_concurrent_yields_one_shown` |
| 10 concurrent checkout confirms | exactly 1 order | `test_concurrency.py::test_concurrent_checkout_confirm_creates_one_order` |
| 10 buyers, 3 units in stock | exactly 3 succeed, stock → 0 | `test_concurrency.py::test_no_oversell_when_many_buyers_race_for_last_unit` |
| Modify cart after checkout confirmed | `409` (locked); `POST /checkout/cancel` to unlock | `test_cart.py::test_cart_locked_after_checkout_confirm` |
| Webhook capture for a cancelled order | not auto-processed; flagged for reconciliation | `test_webhooks.py::test_webhook_on_cancelled_order_never_resurrects_it` |
