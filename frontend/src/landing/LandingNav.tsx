const LINKS = ["Product", "How it works", "Security", "Docs"];

export function LandingNav({ onEnter }: { onEnter: () => void }) {
  return (
    <nav className="lnav">
      <div className="lnav-pill">
        <div className="lnav-brand">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="8" stroke="rgba(255,255,255,0.6)" strokeWidth="1.5" />
            <circle cx="9" cy="9" r="3.5" fill="rgba(255,255,255,0.7)" />
          </svg>
          <span className="lnav-tag"># PAYPILOT</span>
        </div>

        <div className="lnav-sep" />

        {LINKS.map((item) => (
          <button key={item} className="lnav-link" type="button">
            {item}
          </button>
        ))}

        <button className="lnav-link" type="button" onClick={onEnter}>
          Sign in
        </button>

        <button className="lnav-cta" type="button" onClick={onEnter}>
          Get started
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path
              d="M2.5 6h7M6.5 3.5l3 2.5-3 2.5"
              stroke="#0a0a14"
              strokeWidth="1.3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </nav>
  );
}
