import { useEffect, useState } from "react";
import { api, type AuditEntry } from "../lib/api";

export function AuditDrawer({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const [events, setEvents] = useState<AuditEntry[]>([]);
  const [all, setAll] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.audit(all ? undefined : sessionId).then((r) => live && setEvents(r.items));
    load();
    const t = setInterval(load, 2500);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [sessionId, all]);

  return (
    <div className="drawer">
      <header>
        <strong>Audit trail</strong>
        <span className="spacer" />
        <label className="hint" style={{ marginRight: 10 }}>
          <input
            type="checkbox"
            style={{ width: "auto", marginRight: 6 }}
            checked={all}
            onChange={(e) => setAll(e.target.checked)}
          />
          all sessions
        </label>
        <button className="ghost" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="body">
        {events.length === 0 && <p className="hint" style={{ padding: 16 }}>No events yet.</p>}
        {events.map((e) => (
          <div className="event" key={e.id}>
            <div className="top">
              <span className="hint">{e.created_at?.slice(11, 19)}</span>
              <span className="actor">{e.actor}</span>
              <span className="action">{e.action}</span>
            </div>
            <div className="reason">{e.reason}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
