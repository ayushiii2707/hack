import { useEffect, useState } from "react";
import { api, type AuditEntry } from "../lib/api";

export function AuditDrawer({ onClose }: { onClose: () => void }) {
  const [events, setEvents] = useState<AuditEntry[]>([]);

  useEffect(() => {
    let live = true;
    const load = () => api.audit().then((r) => live && setEvents(r.items)).catch(() => {});
    load();
    const t = setInterval(load, 2500);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="drawer">
      <header>
        <strong>Audit trail</strong>
        <span className="hint">· this session</span>
        <span className="spacer" />
        <button className="ghost" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="body">
        {events.length === 0 && (
          <p className="hint" style={{ padding: 18 }}>
            No events yet — every backend action will appear here, newest first.
          </p>
        )}
        {events.map((e) => (
          <div className="event" key={e.id}>
            <div className="top">
              <span className="e-time">{e.created_at?.slice(11, 19)}</span>
              <span className="e-actor">{e.actor}</span>
              <span className="e-action">{e.action}</span>
            </div>
            <div className="e-reason">{e.reason}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
