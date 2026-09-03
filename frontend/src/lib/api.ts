/** Typed backend client. The frontend NEVER computes authoritative totals
 *  or decides payment success. Every stateful call carries the session bearer
 *  token; the backend derives the cart / order from it. */

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
const TOKEN_KEY = "cc.session_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: "include",
    ...init,
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const err = body?.error ?? {};
    throw new ApiError(err.code ?? "ERROR", err.message ?? res.statusText, res.status);
  }
  return body as T;
}

// ---- types (mirror backend schemas) ----
export interface Product {
  id: string;
  name: string;
  description: string;
  category: string;
  brand: string;
  price: number;
  price_display: string;
  currency: string;
  image_url: string;
  stock: number;
  in_stock: boolean;
  tags: string[];
  active: boolean;
}
export interface CartLine {
  product_id: string;
  name: string;
  quantity: number;
  unit_price: number;
  unit_price_display: string;
  line_total: number;
  line_total_display: string;
}
export interface CartTotals {
  currency: string;
  subtotal: number;
  shipping: number;
  tax: number;
  total: number;
  subtotal_display: string;
  shipping_display: string;
  total_display: string;
  free_shipping_threshold: number;
  free_shipping_applied: boolean;
}
export interface Cart {
  cart_id: string;
  session_id: string;
  status: string;
  items: CartLine[];
  totals: CartTotals;
}
export interface SessionInfo {
  session_id: string;
  state: string;
  cart_id: string;
  upsell_shown: boolean;
  upsell_accepted: boolean;
  upsell_declined: boolean;
}
export interface SessionCreated extends SessionInfo {
  session_token: string;
}
export interface UIAction {
  type: "SHOW_PRODUCTS" | "SHOW_CART" | "SHOW_UPSELL" | "SHOW_CHECKOUT" | "SHOW_PAYMENT" | "SHOW_ERROR";
  payload: Record<string, unknown>;
}
export interface AgentReply {
  message: string;
  state: string;
  actions: UIAction[];
  tool_calls: string[];
}
export interface Upsell {
  available: boolean;
  product?: Product;
  reason?: string;
  price_cap?: number;
  price_cap_display?: string;
  score?: number;
  breakdown?: Record<string, unknown>;
}
export interface CheckoutReview {
  session_id: string;
  cart_id: string;
  items: CartLine[];
  totals: CartTotals;
  upsell_available: boolean;
  upsell_pending: boolean;
  issues: unknown[];
  ready_for_payment: boolean;
  has_open_order: boolean;
}
export interface OrderInfo {
  order_id: string;
  session_id: string;
  cart_id: string;
  status: string;
  amount: number;
  amount_display: string;
  currency: string;
  subtotal: number;
  shipping: number;
  tax: number;
  razorpay_order_id: string | null;
  receipt: string | null;
}
export interface PaymentInit {
  key_id: string;
  razorpay_order_id: string;
  order_id: string;
  amount: number;
  amount_display: string;
  currency: string;
  name: string;
  description: string;
  notes: Record<string, unknown>;
}
export interface ConfirmCheckout {
  order: OrderInfo;
  payment: PaymentInit | null;
}
export interface VerifyResult {
  success: boolean;
  order_status: string;
  payment_status: string;
  attempt_number: number;
  message: string;
}
export interface PaymentAttempt {
  id: string;
  attempt_number: number;
  method: string;
  status: string;
  razorpay_payment_id: string | null;
  razorpay_payment_link_id: string | null;
  payment_link_url: string | null;
  failure_reason: string | null;
  settled_amount: number | null;
  created_at: string | null;
}
export interface PaymentLink {
  payment_link_id: string;
  short_url: string | null;
  amount: number;
  currency: string;
  reused: boolean;
}
export interface AuditEntry {
  id: string;
  session_id: string | null;
  order_id: string | null;
  request_id: string | null;
  actor: string;
  action: string;
  reason: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export const api = {
  health: () =>
    req<{ razorpay_configured: boolean; razorpay_webhook_secured: boolean; gemini_configured: boolean }>(
      "/health",
    ),

  async ensureSession(): Promise<SessionInfo> {
    if (getToken()) {
      try {
        return await req<SessionInfo>("/sessions/me");
      } catch {
        setToken(null);
      }
    }
    const created = await req<SessionCreated>("/sessions", { method: "POST" });
    setToken(created.session_token);
    return created;
  },
  resetSession() {
    setToken(null);
  },

  searchProducts: (q: string) =>
    req<{ items: Product[]; count: number }>(`/products/search?q=${encodeURIComponent(q)}&limit=12`),
  getProduct: (id: string) => req<Product>(`/products/${id}`),
  getProducts: (ids: string[]) => Promise.all(ids.map((i) => api.getProduct(i))),

  getCart: () => req<Cart>("/cart"),
  addItem: (product_id: string, quantity = 1) =>
    req<Cart>("/cart/items", { method: "POST", body: JSON.stringify({ product_id, quantity }) }),
  updateItem: (productId: string, quantity: number) =>
    req<Cart>(`/cart/items/${productId}`, { method: "PATCH", body: JSON.stringify({ quantity }) }),
  removeItem: (productId: string) => req<Cart>(`/cart/items/${productId}`, { method: "DELETE" }),

  upsell: () => req<Upsell>("/upsell", { method: "POST" }),
  previewUpsell: () => req<Upsell>("/upsell/preview"),
  acceptUpsell: () => req("/upsell/accept", { method: "POST" }),
  declineUpsell: () => req("/upsell/decline", { method: "POST" }),

  review: () => req<CheckoutReview>("/checkout/review", { method: "POST" }),
  summary: () => req<CheckoutReview>("/checkout/summary"),
  confirm: () => req<ConfirmCheckout>("/checkout/confirm", { method: "POST" }),
  cancelCheckout: () => req<void>("/checkout/cancel", { method: "POST" }),

  createPaymentOrder: () => req<PaymentInit>("/payments/order", { method: "POST" }),
  verifyPayment: (p: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) =>
    req<VerifyResult>("/payments/verify", { method: "POST", body: JSON.stringify(p) }),
  reportFailure: (reason: string, razorpay_payment_id?: string) =>
    req<VerifyResult>("/payments/failed", {
      method: "POST",
      body: JSON.stringify({ reason, razorpay_payment_id }),
    }),
  simulateFailure: () => req<VerifyResult>("/payments/simulate-failure", { method: "POST" }),
  paymentLink: () => req<PaymentLink>("/payments/link", { method: "POST" }),
  attempts: () => req<PaymentAttempt[]>("/payments/attempts"),

  chat: (message: string) =>
    req<AgentReply>("/agent/chat", { method: "POST", body: JSON.stringify({ message }) }),

  audit: () => req<{ items: AuditEntry[]; count: number }>("/audit"),
};
