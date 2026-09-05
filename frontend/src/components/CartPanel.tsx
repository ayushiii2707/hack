import type { Cart } from "../lib/api";

export function CartPanel({
  cart,
  busy,
  onQty,
  onRemove,
  onReview,
}: {
  cart: Cart | null;
  busy: boolean;
  onQty: (productId: string, qty: number) => void;
  onRemove: (productId: string) => void;
  onReview: () => void;
}) {
  const t = cart?.totals;
  const empty = !cart || cart.items.length === 0;
  return (
    <section className="block">
      <div className="block-title">
        <span>🛒</span> Cart {cart ? `· ${cart.items.length} item${cart.items.length === 1 ? "" : "s"}` : ""}
      </div>
      <div>
        {empty && (
          <div className="cart-empty">
            <div className="ring">🛒</div>
            Your cart is empty — ask the assistant to add something.
          </div>
        )}
        {!empty &&
          cart!.items.map((li) => (
            <div className="line" key={li.product_id}>
              <div className="l-name">
                <div>{li.name}</div>
                <div className="hint">{li.unit_price_display} each</div>
              </div>
              <div className="qty">
                <button disabled={busy} onClick={() => onQty(li.product_id, li.quantity - 1)}>
                  −
                </button>
                <span>{li.quantity}</span>
                <button disabled={busy} onClick={() => onQty(li.product_id, li.quantity + 1)}>
                  +
                </button>
              </div>
              <div className="l-total">{li.line_total_display}</div>
              <button className="l-x" disabled={busy} onClick={() => onRemove(li.product_id)}>
                ✕
              </button>
            </div>
          ))}

        {t && (
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
            <p className="hint lock-note">🔒 Totals are calculated and locked by the backend.</p>
          </div>
        )}

        {!empty && (
          <button className="primary cart-cta" disabled={busy} onClick={onReview}>
            Review &amp; Checkout
          </button>
        )}
      </div>
    </section>
  );
}
