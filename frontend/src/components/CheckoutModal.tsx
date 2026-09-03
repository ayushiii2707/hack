import type { CheckoutReview, PaymentAttempt, VerifyResult } from "../lib/api";

export type CheckoutPhase = "review" | "paying" | "result";

export function CheckoutModal({
  review,
  phase,
  result,
  attempts,
  paymentLinkUrl,
  busy,
  razorpayReady,
  onPay,
  onRetry,
  onPaymentLink,
  onSimulateFailure,
  onClose,
  onDone,
}: {
  review: CheckoutReview;
  phase: CheckoutPhase;
  result: VerifyResult | null;
  attempts: PaymentAttempt[];
  paymentLinkUrl: string | null;
  busy: boolean;
  razorpayReady: boolean;
  onPay: () => void;
  onRetry: () => void;
  onPaymentLink: () => void;
  onSimulateFailure: () => void;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = review.totals;
  const paid = !!result?.success && result.order_status === "PAID";
  const failed = phase === "result" && !!result && !result.success;

  return (
    <div className="overlay">
      <div className="modal">
        <header>{paid ? "Payment complete" : failed ? "Payment failed" : "Order review"}</header>
        <div className="body">
          {phase === "review" && (
            <>
              {review.items.map((li) => (
                <div className="line" key={li.product_id}>
                  <div style={{ flex: 1 }}>
                    {li.name} <span className="hint">× {li.quantity}</span>
                  </div>
                  <div>{li.line_total_display}</div>
                </div>
              ))}
              <div className="totals">
                <div className="row">
                  <span>Subtotal</span>
                  <span>{t.subtotal_display}</span>
                </div>
                <div className="row">
                  <span>Shipping {t.free_shipping_applied ? "(free)" : ""}</span>
                  <span>{t.shipping_display}</span>
                </div>
                <div className="row grand">
                  <span>Total</span>
                  <span>{t.total_display}</span>
                </div>
              </div>
              <p className="hint">
                You’ll pay exactly {t.total_display}. Nothing is charged until you complete Razorpay
                checkout.
              </p>
              {review.upsell_pending && (
                <p className="err-text">Please accept or decline the suggested add-on first.</p>
              )}
              {!razorpayReady && (
                <p className="hint">
                  Razorpay test keys aren’t configured on the server — use “Get payment link”.
                </p>
              )}
            </>
          )}

          {phase === "paying" && (
            <div className="result">
              <div className="icon">⏳</div>
              <p>Waiting for the Razorpay payment window…</p>
            </div>
          )}

          {phase === "result" && (
            <div className={`result ${paid ? "ok" : "fail"}`}>
              <div className="icon">{paid ? "✓" : "✕"}</div>
              <h3>{paid ? "Payment successful" : "Payment was not completed"}</h3>
              <p className="hint">{result?.message}</p>
              {failed && (
                <p className="hint">
                  Your order was <strong>not</strong> marked as paid. Retry, or pay via a link.
                </p>
              )}
            </div>
          )}

          {attempts.length > 0 && (
            <div className="attempts">
              <div className="hint">Payment attempts</div>
              {attempts.map((a) => (
                <div className="a" key={a.id}>
                  <span>
                    #{a.attempt_number} · {a.method}
                    {a.failure_reason ? ` — ${a.failure_reason}` : ""}
                  </span>
                  <span className={`tag ${a.status}`}>{a.status}</span>
                </div>
              ))}
            </div>
          )}

          {paymentLinkUrl && (
            <p style={{ marginTop: 12 }}>
              Payment link:{" "}
              <a href={paymentLinkUrl} target="_blank" rel="noreferrer">
                {paymentLinkUrl}
              </a>
            </p>
          )}
        </div>

        <div className="foot">
          {phase === "review" && (
            <>
              <button className="ghost" onClick={onClose} disabled={busy}>
                Back
              </button>
              <button onClick={onSimulateFailure} disabled={busy || !review.ready_for_payment}>
                Demo: force failure
              </button>
              <button className="primary" onClick={onPay} disabled={busy || !review.ready_for_payment}>
                Proceed to Payment · {t.total_display}
              </button>
            </>
          )}

          {failed && (
            <>
              <button onClick={onPaymentLink} disabled={busy}>
                Get payment link
              </button>
              <button className="primary" onClick={onRetry} disabled={busy}>
                Retry payment
              </button>
            </>
          )}

          {paid && (
            <button className="primary" onClick={onDone}>
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
