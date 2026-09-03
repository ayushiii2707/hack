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
    return <p className="hint">Ask the assistant to find something, e.g. “show me running shoes under ₹3000”.</p>;
  }
  return (
    <div className="grid">
      {products.map((p) => (
        <div className="card" key={p.id}>
          {p.image_url ? <img src={p.image_url} alt={p.name} loading="lazy" /> : <div className="card-img" />}
          <div className="name">{p.name}</div>
          <div className="meta">
            {p.brand || p.category}
          </div>
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
