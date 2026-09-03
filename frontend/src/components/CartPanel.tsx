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
      <div className="block-title">🛒 Cart {cart ? `· ${cart.items.length} item(s)` : ""}</div>
      <div>
        {empty && <p className="hint">Your cart is empty.</p>}
        {!empty &&
          cart!.items.map((li) => (
            <div className="line" key={li.product_id}>
              <div style={{ flex: 1 }}>
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
              <div style={{ width: 90, textAlign: "right" }}>{li.line_total_display}</div>
              <button className="ghost" disabled={busy} onClick={() => onRemove(li.product_id)}>
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
            <p className="hint">Totals are calculated and locked by the backend.</p>
          </div>
        )}

        {!empty && (
          <button className="primary" style={{ marginTop: 12, width: "100%" }} disabled={busy} onClick={onReview}>
            Review &amp; Checkout
          </button>
        )}
      </div>
    </section>
  );
}
