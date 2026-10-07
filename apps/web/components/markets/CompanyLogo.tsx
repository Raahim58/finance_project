"use client";

import { useState } from "react";
import { websiteHost } from "@/lib/markets";
import styles from "./markets.module.css";

// Logos come from the company's own stored website. A missing site or a failed/placeholder
// image falls back to a symbol monogram rather than a made-up mark.
export function CompanyLogo({ symbol, website, size = 26 }: { symbol: string; website?: string | null; size?: number }) {
  const host = websiteHost(website);
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  if (!host || failed) return <span className={styles.monogram} style={box} aria-hidden="true">{symbol.slice(0, 2)}</span>;
  return <span className={styles.logo} style={box}>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`} alt="" width={size - 6} height={size - 6} loading="lazy" referrerPolicy="no-referrer"
      onLoad={event => { if (event.currentTarget.naturalWidth <= 16) setFailed(true); }} onError={() => setFailed(true)} />
  </span>;
}
