import type { CSSProperties } from "react";
import type { Product } from "../lib/api";

export function ProductGrid({
  products,
  onAdd,
  busy,
}: {
  products: Product[];
  onAdd: (p: Product) => void;
  busy: boolean;
}) {
  if (products.length === 0) {
    return (
      <p className="hint">
        Ask the assistant to find something, e.g. “find me a laptop under ₹60,000”.
      </p>
    );
  }
  return (
    <div className="grid">
      {products.map((p, i) => (
        <div className="card" key={p.id} style={{ "--i": i } as CSSProperties}>
          <div className={`thumb${p.image_url ? "" : " placeholder"}`}>
            {p.image_url && <img src={p.image_url} alt={p.name} loading="lazy" />}
          </div>
          <div className="name">{p.name}</div>
          <div className="meta">{p.brand || p.category}</div>
          <div className="price">{p.price_display}</div>
          <div className="row">
            {p.in_stock ? (
              <button className="primary" disabled={busy} onClick={() => onAdd(p)}>
                Add to cart
              </button>
            ) : (
              <span className="hint">Out of stock</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
