import { useEffect, useRef, useState } from "react";

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
}

const SUGGESTIONS = [
  "Show me running shoes under ₹3000",
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
      <header>💬 Checkout Copilot</header>
      <div className="messages">
        {messages.length === 0 && (
          <div className="msg assistant">
            Hi! I can help you find products, build your cart, and check out with a real (test-mode)
            payment. Try one of the suggestions below.
          </div>
        )}
        {messages.map((m, i) => (
          <div className={`msg ${m.role}`} key={i}>
            {m.role === "tool" ? `⚙︎ ${m.content}` : m.content}
          </div>
        ))}
        {busy && <div className="msg assistant">…</div>}
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
          placeholder="Message Checkout Copilot…"
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
