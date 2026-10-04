"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getCompanies, type Company, type Portfolio } from "@/lib/api";
import { Icon } from "@/components/Icon";
import type { OverviewUser } from "./useOverviewData";
import styles from "./overview.module.css";

export function OverviewToolbar({ portfolios, portfolioId, onSelect, user, loading }: {
  portfolios: Portfolio[]; portfolioId: string; onSelect: (id: string) => void;
  user: OverviewUser | null; loading: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Company[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    setResults([]);
    if (!query.trim()) { setStatus("idle"); return; }
    const controller = new AbortController();
    setStatus("loading");
    const timer = setTimeout(() => {
      void getCompanies(query.trim(), { signal: controller.signal }).then(rows => {
        if (!controller.signal.aborted) { setResults(rows.slice(0, 6)); setStatus("ready"); }
      }).catch(() => { if (!controller.signal.aborted) setStatus("error"); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);
  const name = user?.full_name?.trim() || user?.email || "Account";
  const initials = user?.full_name?.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase() || user?.email?.[0]?.toUpperCase();
  return <div className={styles.toolbar}>
    <div className={styles.search} onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
      <Icon name="search" size={18} />
      <input aria-label="Find a company" placeholder="Find a company…" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") { setQuery(""); setFocused(false); } }} aria-expanded={focused && Boolean(query.trim())} aria-controls="overview-company-results" autoComplete="off" />
      {focused && query.trim() ? <div id="overview-company-results" className={styles.searchResults} aria-label="Company search results">
        {status === "loading" ? <p role="status">Searching companies…</p> : status === "error" ? <p role="alert">Company search unavailable. Try again.</p> : results.length ? results.map(company => <Link key={company.id} href={`/companies/${encodeURIComponent(company.symbol)}` as never} onClick={() => { setQuery(""); setFocused(false); }}><strong>{company.symbol}</strong><span>{company.name}</span><Icon name="chevron" size={14} /></Link>) : <p>No matching companies.</p>}
      </div> : null}
    </div>
    <label className={styles.portfolioSelect}><Icon name="briefcase" size={17} /><span className="sr-only">Overview portfolio</span><select value={portfolioId} onChange={event => onSelect(event.target.value)} disabled={loading || !portfolios.length}><option value="">{loading ? "Loading portfolios…" : "Select a portfolio"}</option>{portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
    <Link href="/monitoring" className={styles.utilityButton} aria-label="Open monitoring"><Icon name="bell" size={20} /></Link>
    <Link href="/settings" className={styles.avatar} aria-label={`Account settings: ${name}`} title={name}>{initials || <Icon name="settings" size={18} />}</Link>
  </div>;
}
