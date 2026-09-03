import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatPanel, type ChatMessage } from "./components/ChatPanel";
import { ProductGrid } from "./components/ProductGrid";
import { CartPanel } from "./components/CartPanel";
import { UpsellCard } from "./components/UpsellCard";
import { CheckoutModal, type CheckoutPhase } from "./components/CheckoutModal";
import { AuditDrawer } from "./components/AuditDrawer";
import {
  ApiError,
  api,
  type Cart,
  type CheckoutReview,
  type OrderInfo,
  type PaymentAttempt,
  type PaymentInit,
  type Product,
  type SessionInfo,
  type Upsell,
  type VerifyResult,
} from "./lib/api";
import { openRazorpayCheckout, razorpayAvailable } from "./lib/razorpay";

const SESSION_KEY = "cc.session_id";

export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [health, setHealth] = useState<{ razorpay_configured: boolean; gemini_configured: boolean } | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [upsell, setUpsell] = useState<Upsell | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);

  // checkout state
  const [review, setReview] = useState<CheckoutReview | null>(null);
  const [order, setOrder] = useState<OrderInfo | null>(null);
  const [phase, setPhase] = useState<CheckoutPhase>("review");
  const [payResult, setPayResult] = useState<VerifyResult | null>(null);
  const [attempts, setAttempts] = useState<PaymentAttempt[]>([]);
  const [paymentLinkUrl, setPaymentLinkUrl] = useState<string | null>(null);

  const refreshCart = useCallback(async (cartId: string) => {
    setCart(await api.getCart(cartId));
  }, []);

  const bootstrap = useCallback(async () => {
    setHealth(await api.health().catch(() => null));
    const saved = localStorage.getItem(SESSION_KEY);
    let s: SessionInfo | null = null;
    if (saved) s = await api.getSession(saved).catch(() => null);
    if (!s) {
      s = await api.createSession();
      localStorage.setItem(SESSION_KEY, s.session_id);
    }
    setSession(s);
    await refreshCart(s.cart_id);
  }, [refreshCart]);

  useEffect(() => {
    bootstrap().catch((e) => setError(String(e)));
  }, [bootstrap]);

  const withBusy = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  };

  const [checkoutHint, setCheckoutHint] = useState(false);

  const applyActions = useCallback(
    async (actions: { type: string; payload: Record<string, unknown> }[], cartId: string) => {
      for (const a of actions) {
        if (a.type === "SHOW_PRODUCTS") {
          const ids = (a.payload.product_ids as string[]) ?? [];
          if (ids.length) setProducts(await api.getProducts(ids).catch(() => []));
        } else if (a.type === "SHOW_CART" || a.type === "SHOW_CHECKOUT") {
          await refreshCart(cartId);
        }
        if (a.type === "SHOW_CHECKOUT") setCheckoutHint(true);
        if (a.type === "SHOW_UPSELL") {
          const pid = a.payload.product_id as string | undefined;
          if (pid) {
            const product = await api.getProduct(pid).catch(() => undefined);
            if (product)
              setUpsell({
                available: true,
                product,
                reason: (a.payload.reason as string) ?? "A useful add-on for your cart.",
              });
          }
        }
      }
    },
    [refreshCart],
  );

  const send = async (text: string) => {
    if (!session) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    const reply = await withBusy(() => api.chat(session.session_id, text));
    if (!reply) return;
    setMessages((m) => [
      ...m,
      ...(reply.tool_calls.length ? [{ role: "tool" as const, content: reply.tool_calls.join(", ") }] : []),
      { role: "assistant", content: reply.message },
    ]);
    await applyActions(reply.actions, session.cart_id);
    setSession(await api.getSession(session.session_id));
  };

  // ---- cart ops ----
  const addToCart = (p: Product) =>
    withBusy(async () => {
      if (!session) return;
      setCart(await api.addItem(session.cart_id, p.id, 1));
      setSession(await api.getSession(session.session_id));
    });
  const setQty = (productId: string, qty: number) =>
    withBusy(async () => {
      if (!session) return;
      setCart(qty <= 0 ? await api.removeItem(session.cart_id, productId) : await api.updateItem(session.cart_id, productId, qty));
    });
  const removeItem = (productId: string) =>
    withBusy(async () => {
      if (!session) return;
      setCart(await api.removeItem(session.cart_id, productId));
    });

  // ---- upsell ----
  const acceptUpsell = () =>
    withBusy(async () => {
      if (!session || !upsell?.product) return;
      await api.acceptUpsell(session.session_id);
      setCart(await api.addItem(session.cart_id, upsell.product.id, 1));
      setUpsell(null);
      setSession(await api.getSession(session.session_id));
      if (review) setReview(await api.summary(session.session_id));
    });
  const declineUpsell = () =>
    withBusy(async () => {
      if (!session) return;
      await api.declineUpsell(session.session_id);
      setUpsell(null);
      setSession(await api.getSession(session.session_id));
      if (review) setReview(await api.summary(session.session_id));
    });

  // ---- checkout ----
  const openReview = async () => {
    if (!session) return;
    const r = await withBusy(() => api.review(session.session_id));
    if (!r) return;
    setReview(r);
    setPhase("review");
    setPayResult(null);
    setPaymentLinkUrl(null);
    setCheckoutHint(false);
    // If an upsell is available and not yet shown, surface it in the panel.
    if (r.upsell_available && !upsell) {
      const u = await api.upsell(session.session_id).catch(() => null);
      if (u?.available) setUpsell(u);
      setReview(await api.summary(session.session_id));
    }
  };

  const startPayment = () =>
    withBusy(async () => {
      if (!session) return;
      const confirmed = await api.confirm(session.session_id);
      setOrder(confirmed.order);      setAttempts(await api.attempts(confirmed.order.order_id).catch(() => []));
      if (!confirmed.payment) {
        setError("Razorpay is not configured on the server. Use “Get payment link”.");
        setPhase("result");
        setPayResult({
          success: false,
          order_status: confirmed.order.status,
          payment_status: "CREATED",
          attempt_number: 0,
          message: "Razorpay not configured — try the payment link fallback.",
        });
        return;
      }
      launchRazorpay(confirmed.payment, confirmed.order.order_id);
    });

  const launchRazorpay = (init: PaymentInit, orderId: string) => {
    setPhase("paying");
    openRazorpayCheckout({
      init,
      onSuccess: async (r) => {
        const res = await api.verifyPayment({
          order_id: orderId,
          razorpay_order_id: r.razorpay_order_id,
          razorpay_payment_id: r.razorpay_payment_id,
          razorpay_signature: r.razorpay_signature,
        });
        setPayResult(res);
        setAttempts(await api.attempts(orderId).catch(() => []));
        setPhase("result");
        if (res.success && session) setSession(await api.getSession(session.session_id));
      },
      onFailure: async (reason, paymentId) => {
        const res = await api.reportFailure(orderId, reason, paymentId).catch(() => null);
        setPayResult(
          res ?? {
            success: false,
            order_status: "PAYMENT_FAILED",
            payment_status: "FAILED",
            attempt_number: 0,
            message: reason,
          },
        );
        setAttempts(await api.attempts(orderId).catch(() => []));
        setPhase("result");
      },
      onDismiss: () => setPhase("review"),
    });
  };

  const retryPayment = () =>
    withBusy(async () => {
      if (!session) return;
      const confirmed = await api.confirm(session.session_id); // idempotent
      setOrder(confirmed.order);
      if (confirmed.payment) {        launchRazorpay(confirmed.payment, confirmed.order.order_id);
      }
    });

  const getPaymentLink = () =>
    withBusy(async () => {
      if (!order) return;
      const link = await api.paymentLink(order.order_id);
      setPaymentLinkUrl(link.short_url ?? null);
      setAttempts(await api.attempts(order.order_id).catch(() => []));
      if (link.short_url) window.open(link.short_url, "_blank");
    });

  const forceFailure = () =>
    withBusy(async () => {
      if (!session) return;
      const confirmed = await api.confirm(session.session_id);
      setOrder(confirmed.order);
      const res = await api.simulateFailure(confirmed.order.order_id);
      setPayResult(res);
      setAttempts(await api.attempts(confirmed.order.order_id).catch(() => []));
      setPhase("result");
    });

  const closeCheckout = () => {
    setReview(null);
    setPhase("review");
  };
  const finishCheckout = async () => {
    closeCheckout();
    if (session) {
      await refreshCart(session.cart_id);
      setSession(await api.getSession(session.session_id));
    }
    setMessages((m) => [...m, { role: "assistant", content: "🎉 Payment complete — your order is confirmed." }]);
  };

  const showUpsellPanel = useMemo(
    () => upsell?.available && !session?.upsell_accepted && !session?.upsell_declined,
    [upsell, session],
  );

  return (
    <div className="app">
      <div className="topbar">
        <h1>Checkout Copilot</h1>
        <span className={`badge ${health?.gemini_configured ? "on" : "off"}`}>
          Gemini {health?.gemini_configured ? "ready" : "off"}
        </span>
        <span className={`badge ${health?.razorpay_configured ? "on" : "off"}`}>
          Razorpay {health?.razorpay_configured ? "test-mode" : "off"}
        </span>
        <span className="badge">state: {session?.state ?? "…"}</span>
        <span className="spacer" />
        <button className="ghost" onClick={() => setAuditOpen(true)}>
          Audit trail
        </button>
        <button
          className="ghost"
          onClick={() => {
            localStorage.removeItem(SESSION_KEY);
            location.reload();
          }}
        >
          New session
        </button>
      </div>

      {error && (
        <div style={{ padding: "8px 16px", color: "var(--err)", fontSize: 13 }}>{error}</div>
      )}

      <div className="layout">
        <ChatPanel messages={messages} busy={busy} onSend={send} />

        <div className="panel">
          <header>🛍️ Store</header>
          <div className="body store-body">
            {checkoutHint && !review && (
              <div className="upsell" style={{ borderColor: "var(--accent-2)" }}>
                <div>The assistant moved you to checkout review.</div>
                <button className="primary" onClick={openReview} disabled={busy}>
                  Open order review
                </button>
              </div>
            )}
            {showUpsellPanel && upsell && (
              <UpsellCard upsell={upsell} busy={busy} onAccept={acceptUpsell} onDecline={declineUpsell} />
            )}
            <CartPanel
              cart={cart}
              busy={busy}
              onQty={setQty}
              onRemove={removeItem}
              onReview={openReview}
            />
            <section className="block">
              <div className="block-title">🛍️ Results</div>
              <ProductGrid products={products} onAdd={addToCart} busy={busy} />
            </section>
          </div>
        </div>
      </div>

      {review && (
        <CheckoutModal
          review={review}
          phase={phase}
          result={payResult}
          attempts={attempts}
          paymentLinkUrl={paymentLinkUrl}
          busy={busy}
          razorpayReady={!!health?.razorpay_configured && razorpayAvailable()}
          onPay={startPayment}
          onRetry={retryPayment}
          onPaymentLink={getPaymentLink}
          onSimulateFailure={forceFailure}
          onClose={closeCheckout}
          onDone={finishCheckout}
        />
      )}

      {auditOpen && session && (
        <AuditDrawer sessionId={session.session_id} onClose={() => setAuditOpen(false)} />
      )}
    </div>
  );
}
