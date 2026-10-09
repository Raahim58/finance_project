"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { searchInstruments } from "@/lib/api";
import styles from "./company.module.css";

type Match = { id: string; symbol: string; name: string };

export function CompanySearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 1) { setMatches([]); return; }
    let active = true;
    const timer = setTimeout(() => {
      void searchInstruments(term).then(rows => { if (active) setMatches(rows.slice(0, 8)); }).catch(() => { if (active) setMatches([]); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [query]);

  useEffect(() => {
    const close = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);

  const go = (symbol: string) => { setOpen(false); setQuery(""); router.push(`/companies/${encodeURIComponent(symbol)}` as never); };
  return <div className={styles.search} ref={box}>
    <input aria-label="Search companies" placeholder="Search" value={query} autoComplete="off"
      onChange={event => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
      onKeyDown={event => { if (event.key === "Enter" && matches[0]) go(matches[0].symbol); if (event.key === "Escape") setOpen(false); }} />
    {open && query.trim() && matches.length ? <ul role="listbox">{matches.map(row => <li key={row.id}><button type="button" role="option" aria-selected={false} onClick={() => go(row.symbol)}><b>{row.symbol}</b><span>{row.name}</span></button></li>)}</ul> : null}
  </div>;
}
