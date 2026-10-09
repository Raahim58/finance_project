"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { acknowledgeAlert, getAlerts, getPortfolios, getPreferences, runMonitoring } from "@/lib/api";
import { topicEnabled } from "@/components/settings/providers";
import { timeAgo } from "@/lib/markets";

type AlertRow = { id: string; portfolio_id: string; alert_type: string; severity: string; message: string; created_at: string; data_as_of?: string | null };
const POLL_MS = 60_000;

export function NotificationBell() {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [rows, prefs] = await Promise.all([getAlerts(undefined, "active"), getPreferences()]);
      const topics = prefs.notification_preferences as Record<string, boolean> | undefined;
      setAlerts((rows as unknown as AlertRow[]).filter(row => topicEnabled(topics, row.alert_type)));
      setError(false);
    } catch { setError(true); }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    for (const event of ["psx-auth-change", "psx-notification-prefs", "psx-portfolio-change"]) window.addEventListener(event, refresh);
    return () => { window.clearInterval(timer); for (const event of ["psx-auth-change", "psx-notification-prefs", "psx-portfolio-change"]) window.removeEventListener(event, refresh); };
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const esc = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function runChecks() {
    setChecking(true);
    try {
      const portfolio = (await getPortfolios()).find(row => row.is_default && !row.archived_at);
      if (portfolio) await runMonitoring(portfolio.id);
      await refresh();
    } catch { setError(true); }
    finally { setChecking(false); }
  }

  async function dismiss(id: string) {
    setAlerts(rows => rows.filter(row => row.id !== id));
    try { await acknowledgeAlert(id); } catch { void refresh(); }
  }

  return (
    <div ref={root} className="notif">
      <button type="button" className="icon-btn notif-btn" aria-label={`Notifications${alerts.length ? `, ${alerts.length} active` : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="bell" />{alerts.length ? <span className="notif-count">{alerts.length > 9 ? "9+" : alerts.length}</span> : null}
      </button>
      {open ? (
        <div className="notif-panel rx" role="dialog" aria-label="Notifications">
          <div className="notif-head"><strong>Notifications</strong><Link className="rx-link" href={"/settings?section=notifications" as never} onClick={() => setOpen(false)}>Settings</Link></div>
          <div className="notif-item"><small style={{ textTransform: "none" }}>Checks evaluate your monitoring rules against stored data.</small><button type="button" className="rx-btn rx-btn-outline rx-btn-sm" disabled={checking} onClick={runChecks}>{checking ? "Checking…" : "Run checks now"}</button></div>
          {error ? <p className="notif-empty">Alerts could not be loaded.</p> : null}
          {!error && !alerts.length ? <p className="notif-empty">No active alerts. Alerts appear when a monitoring rule triggers.</p> : null}
          {alerts.map(alert => (
            <div className="notif-item" key={alert.id}>
              <div>
                <p>{alert.message}</p>
                <small>{alert.alert_type.replaceAll("_", " ")} · {timeAgo(alert.created_at) ?? alert.created_at}{alert.data_as_of ? ` · data as of ${alert.data_as_of}` : ""}</small>
              </div>
              <div className="notif-actions">
                <Link href={`/portfolios/${alert.portfolio_id}/activity` as never} className="rx-link" onClick={() => setOpen(false)}>View</Link>
                <button type="button" className="rx-link-quiet" onClick={() => dismiss(alert.id)}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
