import { useCallback, useEffect, useRef, useState } from "react";
import { ParticleScene } from "./ParticleScene";
import { LandingNav } from "./LandingNav";
import "./landing.css";

function useTypewriter(text: string, speed = 30, delay = 1200) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => {
    let i = 0;
    setDisplayed("");
    setDone(false);
    let interval: ReturnType<typeof setInterval> | undefined;
    const timeout = setTimeout(() => {
      interval = setInterval(() => {
        i++;
        setDisplayed(text.slice(0, i));
        if (i >= text.length) {
          if (interval) clearInterval(interval);
          setDone(true);
        }
      }, speed);
    }, delay);
    return () => {
      clearTimeout(timeout);
      if (interval) clearInterval(interval);
    };
  }, [text, speed, delay]);
  return { displayed, done };
}

const HEADING = "Everything revolves around one thing — the checkout.";

export function Landing({ onEnter }: { onEnter: () => void }) {
  const scrollRef = useRef(0);
  const { displayed, done } = useTypewriter(HEADING);

  const onScroll = useCallback(() => {
    const el = document.documentElement;
    const max = el.scrollHeight - el.clientHeight;
    scrollRef.current = max > 0 ? el.scrollTop / max : 0;
  }, []);

  useEffect(() => {
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [onScroll]);

  return (
    <div className="landing">
      {/* scroll runway — gives the fixed scene something to react to */}
      <div className="landing-runway" />

      <ParticleScene scrollRef={scrollRef} />

      {/* gradient wash: transparent at top, deep black at the base */}
      <div className="landing-wash" />

      {/* white circle that zooms out on first paint */}
      <div className="landing-intro" />

      {/* watermark wordmark, top-left */}
      <div className="landing-watermark">Checkout&nbsp;Copilot</div>

      <LandingNav onEnter={onEnter} />

      <div className="landing-hero">
        <div className="lh-left">
          <h2 className="lh-heading">
            {displayed}
            <span className={`lh-caret${done ? " off" : ""}`}>|</span>
          </h2>
        </div>

        <div className="lh-right">
          <p className="lh-copy">
            A conversational AI agent builds the cart and takes payment while a deterministic
            backend stays the sole authority for pricing, stock, and every payment transition.
            The noise of a checkout, focused to a single point.
          </p>

          <div className={`lh-cta-wrap${done ? " in" : ""}`}>
            <button className="lh-cta" type="button" onClick={onEnter}>
              Let&rsquo;s get started
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                <path
                  d="M2.5 6.5h8M7.5 3.5l3 3-3 3"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
