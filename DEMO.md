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

Open <http://localhost:5173>. Have `.env` filled with **Razorpay test keys**
(and optionally `GEMINI_API_KEY`). Click **New session** for a clean run.

Keep the **Audit trail** panel open on a second monitor / tab — it updates live.

---

## The story

### 1. Conversational discovery (targets Baymard "too complicated")
Type: **"I need running shoes under ₹3000"**
→ agent calls `search_products`, results render as cards.
Audit: `CUSTOMER · PRODUCT_SEARCHED`.

### 2. Build the cart in natural language
Type: **"add the first one"** (or click **Add to cart**).
Audit: `AGENT · ITEM_ADDED` with the price snapshot in paise.

### 3. Authoritative total
Type: **"show me my cart"** → subtotal / shipping / total, all from the backend.
Say: *the frontend never computes this — it only displays what the API returns.*

### 4. Cart review — full price before paying (targets Baymard "hidden costs")
Click **Review & Checkout**. The modal shows every line, shipping, and the
**exact amount you will pay** — before any payment UI appears.

### 5. Exactly one explainable upsell
An upsell card appears once: e.g. *"Since you're buying Nike Baseball Cleats,
Feather Shuttlecock is a practical add-on and stays within your ₹559 budget."*
Point out: concrete reason, price cap = 20% of subtotal, **one** suggestion.
Audit: `AGENT · UPSELL_SHOWN` with `score`, `relevance`, `complementary_score`,
`price_fit`, `price_cap` in the metadata.

### 6. Decline — and it never comes back
Click **No thanks**. Audit: `CUSTOMER · UPSELL_DECLINED`.
Now add another product, or return to review — **no second upsell**.
(Try typing "anything else?" — the agent's `request_upsell` is `POLICY_BLOCKED`.)

### 7. Confirm checkout → real Razorpay Test-Mode order
Click **Proceed to Payment**. Backend:
`CheckoutService.confirm_checkout` (idempotent) → internal `Order` with a
server-computed amount → `PaymentService.ensure_payment_order` → real
`razorpay.order.create` (amount in **paise**). Audit: `SYSTEM · PAYMENT_ATTEMPTED`
with the `razorpay_order_id`.

### 8. Deliberate failure
In Razorpay's test window, choose **Failure** (or use the **Demo: force failure**
button). The UI shows *"Payment was not completed — your order was **not** marked
as paid"*, lists **attempt #1 = FAILED**, and offers **Retry** / **Get payment link**.
DB: `order.status = PAYMENT_FAILED`, `payment.status = FAILED`.
Audit: `SYSTEM · PAYMENT_ATTEMPTED` then `PAYMENT_PROVIDER · PAYMENT_FAILED`.

### 9. Recovery
**Retry payment** → pay with success card `4111 1111 1111 1111`.
Backend verifies the signature (`order_id|payment_id` HMAC-SHA256) — only then:
`order.status = PAID`, **attempt #2 = CAPTURED** (attempt #1 is preserved),
session `COMPLETED`. Audit: `PAYMENT_PROVIDER · PAYMENT_SUCCESS`.

*Alternative:* **Get payment link** → real `razorpay.payment_link.create`,
opens the hosted Razorpay link. Audit: `SYSTEM · PAYMENT_LINK_CREATED`.

### 10. Transparency
Scroll the **Audit trail**. It reads like:

```
CUSTOMER          SESSION_CREATED
CUSTOMER          PRODUCT_SEARCHED     Searched 'running shoes' under ₹3,000.00
AGENT             ITEM_ADDED           Added 1 x 'Nike Baseball Cleats' …
AGENT             UPSELL_SHOWN         Since you're buying Nike Baseball Cleats, …
CUSTOMER          UPSELL_DECLINED      … it will not be shown again.
CUSTOMER          CHECKOUT_STARTED     Authoritative amount 279965 paise.
SYSTEM            PAYMENT_ATTEMPTED    Razorpay order order_… created …
PAYMENT_PROVIDER  PAYMENT_FAILED       Simulated gateway failure …
SYSTEM            PAYMENT_ATTEMPTED    Payment attempt #2 …
PAYMENT_PROVIDER  PAYMENT_SUCCESS      Payment pay_… verified and captured …
```

---

## If a judge asks "can the AI just pay / overcharge / spam upsells?"

- **Pay:** there is no payment tool. `PolicyEngine.can_create_payment()` always
  denies. Payment needs the customer to click in Razorpay's own UI. Test:
  `tests/test_policies.py::test_no_payment_capability_exists`.
- **Overcharge:** the order amount is computed by `PricingService` from cart
  snapshots; `/payments/*` ignores any client amount. Test:
  `test_payments.py::test_razorpay_order_created_with_amount_in_paise`.
- **Quantity abuse:** `add_to_cart(quantity=999999)` → `POLICY_BLOCKED` audit +
  403, nothing added. Test: `test_policies.py::test_quantity_abuse_blocked_and_audited`.
- **Spam upsells:** `session.upsell_shown` is a one-way latch; even a new cart
  can't reset it. Tests: `test_upsell.py::test_cart_change_after_upsell_does_not_reset`,
  `test_policies.py::test_second_upsell_via_tool_blocked`.
- **Fake success:** frontend posting `payment_status=success` without a valid
  signature → `PaymentVerificationError`, order stays unpaid. Test:
  `test_policies.py::test_fake_payment_success_without_verification_not_marked_paid`.
