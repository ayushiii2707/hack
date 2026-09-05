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
      <div className="u-tag">
        <span className="sparkle">✦</span> You might also like
      </div>
      <div className="u-prod">
        {upsell.product.image_url && <img src={upsell.product.image_url} alt="" />}
        <div>
          <div className="u-name">{upsell.product.name}</div>
          <div className="u-price">{upsell.product.price_display}</div>
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
