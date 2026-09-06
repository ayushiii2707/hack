import { useEffect, useRef, useState } from "react";

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
}

const SUGGESTIONS = [
  "Find me a laptop under ₹60,000",
  "Add the first one",
  "Show me my cart",
  "I'm ready to check out",
];

export function ChatPanel({
  messages,
  busy,
  onSend,
}: {
  messages: ChatMessage[];
  busy: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const submit = () => {
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    onSend(t);
  };

  return (
    <div className="panel chat">
      <header>
        <span className="hd-ico">💬</span> PayPilot
      </header>
      <div className={`messages${messages.length === 0 ? " empty" : ""}`}>
        {messages.length === 0 ? (
          <>
            <div className="intro-badge">✦</div>
            <div className="intro-copy">
              Talk naturally to build a cart and pay with a real <strong>test-mode</strong> Razorpay
              checkout. Pricing, stock and every payment step stay locked to the backend.
            </div>
          </>
        ) : (
          messages.map((m, i) => (
            <div className={`msg ${m.role}`} key={i}>
              {m.role === "tool" ? `⚙ ${m.content}` : m.content}
            </div>
          ))
        )}
        {busy && (
          <div className="msg assistant typing">
            <i /><i /><i />
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="suggest">
        {SUGGESTIONS.map((s) => (
          <button key={s} disabled={busy} onClick={() => onSend(s)}>
            {s}
          </button>
        ))}
      </div>
      <div className="composer">
        <input
          value={text}
          placeholder="Message PayPilot…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button className="primary" disabled={busy} onClick={submit}>
          Send
        </button>
      </div>
    </div>
  );
}
