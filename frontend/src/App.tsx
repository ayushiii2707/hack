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
  type PaymentAttempt,
  type PaymentInit,
  type Product,
  type SessionInfo,
  type Upsell,
  type VerifyResult,
} from "./lib/api";
import { openRazorpayCheckout, razorpayAvailable } from "./lib/razorpay";

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
  const [checkoutHint, setCheckoutHint] = useState(false);

  const [review, setReview] = useState<CheckoutReview | null>(null);
  const [phase, setPhase] = useState<CheckoutPhase>("review");
  const [payResult, setPayResult] = useState<VerifyResult | null>(null);
  const [attempts, setAttempts] = useState<PaymentAttempt[]>([]);
  const [paymentLinkUrl, setPaymentLinkUrl] = useState<string | null>(null);

  const refreshCart = useCallback(async () => setCart(await api.getCart()), []);
  const refreshSession = useCallback(async () => {
    setSession(await api.ensureSession());
  }, []);

  useEffect(() => {
    (async () => {
      setHealth(await api.health().catch(() => null));
      setSession(await api.ensureSession());
      await refreshCart();
    })().catch((e) => setError(String(e)));
  }, [refreshCart]);

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

  const applyActions = useCallback(
    async (actions: { type: string; payload: Record<string, unknown> }[]) => {
      for (const a of actions) {
        if (a.type === "SHOW_PRODUCTS") {
          const ids = (a.payload.product_ids as string[]) ?? [];
          if (ids.length) setProducts(await api.getProducts(ids).catch(() => []));
        } else if (a.type === "SHOW_CART" || a.type === "SHOW_CHECKOUT") {
          await refreshCart();
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
    setMessages((m) => [...m, { role: "user", content: text }]);
    const reply = await withBusy(() => api.chat(text));
    if (!reply) return;
    setMessages((m) => [
      ...m,
      ...(reply.tool_calls.length ? [{ role: "tool" as const, content: reply.tool_calls.join(", ") }] : []),
      { role: "assistant", content: reply.message },
    ]);
    await applyActions(reply.actions);
    await refreshSession();
  };

  const addToCart = (p: Product) =>
    withBusy(async () => {
      setCart(await api.addItem(p.id, 1));
      await refreshSession();
    });
  const setQty = (productId: string, qty: number) =>
    withBusy(async () => {
      setCart(qty <= 0 ? await api.removeItem(productId) : await api.updateItem(productId, qty));
    });
  const removeItem = (productId: string) => withBusy(async () => setCart(await api.removeItem(productId)));

  const acceptUpsell = () =>
    withBusy(async () => {
      if (!upsell?.product) return;
      await api.acceptUpsell();
      setCart(await api.addItem(upsell.product.id, 1));
      setUpsell(null);
      await refreshSession();
      if (review) setReview(await api.summary());
    });
  const declineUpsell = () =>
    withBusy(async () => {
      await api.declineUpsell();
      setUpsell(null);
      await refreshSession();
      if (review) setReview(await api.summary());
    });

  const openReview = async () => {
    const r = await withBusy(() => api.review());
    if (!r) return;
    setReview(r);
    setPhase("review");
    setPayResult(null);
    setPaymentLinkUrl(null);
    setCheckoutHint(false);
    if (r.upsell_available && !upsell) {
      const u = await api.upsell().catch(() => null);
      if (u?.available) setUpsell(u);
      setReview(await api.summary());
    }
  };

  const launchRazorpay = (init: PaymentInit) => {
    setPhase("paying");
    openRazorpayCheckout({
      init,
      onSuccess: async (r) => {
        const res = await api.verifyPayment({
          razorpay_order_id: r.razorpay_order_id,
          razorpay_payment_id: r.razorpay_payment_id,
          razorpay_signature: r.razorpay_signature,
        });
        setPayResult(res);
        setAttempts(await api.attempts().catch(() => []));
        setPhase("result");
        if (res.success) await refreshSession();
      },
      onFailure: async (reason, paymentId) => {
        const res = await api.reportFailure(reason, paymentId).catch(() => null);
        setPayResult(
          res ?? {
            success: false,
            order_status: "PAYMENT_FAILED",
            payment_status: "FAILED",
            attempt_number: 0,
            message: reason,
          },
        );
        setAttempts(await api.attempts().catch(() => []));
        setPhase("result");
        await refreshSession();
      },
      onDismiss: () => setPhase("review"),
    });
  };

  const startPayment = () =>
    withBusy(async () => {
      const confirmed = await api.confirm();
      setAttempts(await api.attempts().catch(() => []));
      if (!confirmed.payment) {
        setPhase("result");
        setPayResult({
          success: false,
          order_status: confirmed.order.status,
          payment_status: "CREATED",
          attempt_number: 0,
          message: "Razorpay is not configured on the server — try the payment link.",
        });
        return;
      }
      launchRazorpay(confirmed.payment);
    });

  const retryPayment = () =>
    withBusy(async () => {
      const confirmed = await api.confirm();
      if (confirmed.payment) launchRazorpay(confirmed.payment);
    });

  const getPaymentLink = () =>
    withBusy(async () => {
      const link = await api.paymentLink();
      setPaymentLinkUrl(link.short_url ?? null);
      setAttempts(await api.attempts().catch(() => []));
      if (link.short_url) window.open(link.short_url, "_blank", "noopener,noreferrer");
    });

  const forceFailure = () =>
    withBusy(async () => {
      await api.confirm();
      const res = await api.simulateFailure();
      setPayResult(res);
      setAttempts(await api.attempts().catch(() => []));
      setPhase("result");
      await refreshSession();
    });

  const closeCheckout = () =>
    withBusy(async () => {
      await api.cancelCheckout().catch(() => undefined);
      setReview(null);
      setPhase("review");
      await refreshCart();
      await refreshSession();
    });

  const finishCheckout = async () => {
    setReview(null);
    setPhase("review");
    await refreshCart();
    await refreshSession();
    setMessages((m) => [...m, { role: "assistant", content: "🎉 Payment complete — your order is confirmed." }]);
  };

  const showUpsellPanel = useMemo(
    () => upsell?.available && !session?.upsell_accepted && !session?.upsell_declined,
    [upsell, session],
  );

  return (
    <div className="app">
      <div className="bg-fx" aria-hidden="true">
        <div className="orb a" />
        <div className="orb b" />
        <div className="orb c" />
        <div className="grid-lines" />
        <div className="noise" />
      </div>

      <nav className="nav">
        <div className="wordmark">
          <span className="mark">C</span>
          Checkout&nbsp;<b>Copilot</b>
        </div>
        <span className="divider" />
        <div className="chips">
          <span className={`chip ${health?.gemini_configured ? "on" : "off"}`}>
            <span className="dot" />
            Gemini {health?.gemini_configured ? "ready" : "off"}
          </span>
          <span className={`chip ${health?.razorpay_configured ? "on" : "off"}`}>
            <span className="dot" />
            Razorpay {health?.razorpay_configured ? "test-mode" : "off"}
          </span>
          <span className="chip state">{session?.state ?? "…"}</span>
        </div>
        <span className="spacer" />
        <button className="ghost" onClick={() => setAuditOpen(true)}>
          Audit trail
        </button>
        <button
          className="ghost"
          onClick={() => {
            api.resetSession();
            location.reload();
          }}
        >
          New session
        </button>
      </nav>

      {error && <div className="err-banner">{error}</div>}

      <div className="layout">
        <ChatPanel messages={messages} busy={busy} onSend={send} />

        <div className="panel">
          <header>
            <span className="hd-ico">🛍️</span> Store
          </header>
          <div className="body store-body">
            {checkoutHint && !review && (
              <div className="handoff">
                <span>The assistant moved you to checkout review.</span>
                <button className="primary" onClick={openReview} disabled={busy}>
                  Open order review
                </button>
              </div>
            )}
            {showUpsellPanel && upsell && (
              <UpsellCard upsell={upsell} busy={busy} onAccept={acceptUpsell} onDecline={declineUpsell} />
            )}
            <CartPanel cart={cart} busy={busy} onQty={setQty} onRemove={removeItem} onReview={openReview} />
            <section className="block">
              <div className="block-title">
                <span>🛍️</span> Results
              </div>
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

      {auditOpen && <AuditDrawer onClose={() => setAuditOpen(false)} />}
    </div>
  );
}
