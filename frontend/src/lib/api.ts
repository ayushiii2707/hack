/** Typed backend client. The frontend NEVER computes authoritative totals. */

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

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
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
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
export interface UIAction {
  type:
    | "SHOW_PRODUCTS"
    | "SHOW_CART"
    | "SHOW_UPSELL"
    | "SHOW_CHECKOUT"
    | "SHOW_PAYMENT"
    | "SHOW_ERROR";
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
  actor: string;
  action: string;
  reason: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export const api = {
  health: () => req<{ status: string; razorpay_configured: boolean; gemini_configured: boolean }>("/health"),
  createSession: () => req<SessionInfo>("/sessions", { method: "POST" }),
  getSession: (id: string) => req<SessionInfo>(`/sessions/${id}`),

  chat: (session_id: string, message: string) =>
    req<AgentReply>("/agent/chat", { method: "POST", body: JSON.stringify({ session_id, message }) }),

  searchProducts: (q: string) =>
    req<{ items: Product[]; count: number }>(`/products/search?q=${encodeURIComponent(q)}&limit=12`),
  getProduct: (id: string) => req<Product>(`/products/${id}`),
  getProducts: (ids: string[]) => Promise.all(ids.map((i) => api.getProduct(i))),

  getCart: (cartId: string) => req<Cart>(`/cart/${cartId}`),
  addItem: (cartId: string, product_id: string, quantity = 1) =>
    req<Cart>(`/cart/${cartId}/items`, { method: "POST", body: JSON.stringify({ product_id, quantity }) }),
  updateItem: (cartId: string, productId: string, quantity: number) =>
    req<Cart>(`/cart/${cartId}/items/${productId}`, { method: "PATCH", body: JSON.stringify({ quantity }) }),
  removeItem: (cartId: string, productId: string) =>
    req<Cart>(`/cart/${cartId}/items/${productId}`, { method: "DELETE" }),

  upsell: (sessionId: string, peek = false) =>
    req<Upsell>(`/upsell/${sessionId}${peek ? "?peek=true" : ""}`),
  acceptUpsell: (sessionId: string) => req(`/upsell/${sessionId}/accept`, { method: "POST" }),
  declineUpsell: (sessionId: string) => req(`/upsell/${sessionId}/decline`, { method: "POST" }),

  review: (sessionId: string) => req<CheckoutReview>(`/checkout/${sessionId}/review`, { method: "POST" }),
  summary: (sessionId: string) => req<CheckoutReview>(`/checkout/${sessionId}/summary`),
  confirm: (sessionId: string) => req<ConfirmCheckout>(`/checkout/${sessionId}/confirm`, { method: "POST" }),

  verifyPayment: (p: {
    order_id: string;
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  }) => req<VerifyResult>("/payments/verify", { method: "POST", body: JSON.stringify(p) }),
  reportFailure: (order_id: string, reason: string, razorpay_payment_id?: string) =>
    req<VerifyResult>("/payments/failed", {
      method: "POST",
      body: JSON.stringify({ order_id, reason, razorpay_payment_id }),
    }),
  simulateFailure: (order_id: string) =>
    req<VerifyResult>(`/payments/order/${order_id}/simulate-failure`, { method: "POST" }),
  paymentLink: (order_id: string) =>
    req<PaymentLink>("/payments/link", { method: "POST", body: JSON.stringify({ order_id }) }),
  attempts: (orderId: string) => req<PaymentAttempt[]>(`/payments/order/${orderId}/attempts`),

  audit: (sessionId?: string) =>
    req<{ items: AuditEntry[]; count: number }>(`/audit${sessionId ? `?session_id=${sessionId}` : ""}`),
};
