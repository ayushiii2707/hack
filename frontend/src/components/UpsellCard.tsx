import type { Upsell } from "../lib/api";

export function UpsellCard({
  upsell,
  busy,
  onAccept,
  onDecline,
}: {
  upsell: Upsell;
  busy: boolean;
  onAccept: () => void;
  onDecline: () => void;
}) {
  if (!upsell.available || !upsell.product) return null;
  return (
    <div className="upsell">
      <div>✨ You might also like</div>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        {upsell.product.image_url && (
          <img src={upsell.product.image_url} alt="" style={{ width: 56, height: 56, objectFit: "contain" }} />
        )}
        <div>
          <div style={{ fontWeight: 700 }}>{upsell.product.name}</div>
          <div>{upsell.product.price_display}</div>
        </div>
      </div>
      <div className="why">
        <strong>Why:</strong> {upsell.reason}
        {upsell.price_cap_display && (
          <span className="hint"> (within your {upsell.price_cap_display} add-on budget)</span>
        )}
      </div>
      <div className="actions">
        <button className="primary" disabled={busy} onClick={onAccept}>
          Add to cart
        </button>
        <button disabled={busy} onClick={onDecline}>
          No thanks
        </button>
      </div>
      <p className="hint">One suggestion only — you won’t be asked again this session.</p>
    </div>
  );
}
