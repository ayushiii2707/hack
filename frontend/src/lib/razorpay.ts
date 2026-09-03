/** Thin wrapper over Razorpay Checkout (script loaded in index.html). */
import type { PaymentInit } from "./api";

interface RazorpaySuccess {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

interface OpenArgs {
  init: PaymentInit;
  onSuccess: (r: RazorpaySuccess) => void;
  onFailure: (reason: string, paymentId?: string) => void;
  onDismiss: () => void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare global {
  interface Window {
    Razorpay?: any;
  }
}

export function razorpayAvailable(): boolean {
  return typeof window !== "undefined" && !!window.Razorpay;
}

export function openRazorpayCheckout({ init, onSuccess, onFailure, onDismiss }: OpenArgs) {
  if (!razorpayAvailable()) {
    onFailure("Razorpay Checkout could not load. Use the payment link instead.");
    return;
  }
  const rzp = new window.Razorpay({
    key: init.key_id,
    order_id: init.razorpay_order_id,
    amount: init.amount,
    currency: init.currency,
    name: init.name,
    description: init.description,
    notes: init.notes,
    handler: (resp: RazorpaySuccess) => onSuccess(resp),
    modal: { ondismiss: () => onDismiss() },
    theme: { color: "#4f46e5" },
  });
  rzp.on("payment.failed", (resp: { error?: { description?: string; metadata?: { payment_id?: string } } }) => {
    onFailure(
      resp?.error?.description ?? "Payment failed at the gateway.",
      resp?.error?.metadata?.payment_id,
    );
  });
  rzp.open();
}
