"use client";

import { useState } from "react";
import { websiteHost } from "@/lib/markets";
import styles from "./markets.module.css";
import companyMarks from "@/public/company-marks/sources.json";

// Logos come from the company's own stored website. A missing site or a failed/placeholder
// image falls back to a symbol monogram rather than a made-up mark.
export function CompanyLogo({ symbol, website, size = 26 }: { symbol: string; website?: string | null; size?: number }) {
  const host = websiteHost(website);
  const registered = (companyMarks as Record<string, { asset: string }>)[symbol];
  const src = registered?.asset ?? (host ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64` : null);
  const [failed, setFailed] = useState<string | null>(null);
  const box = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  if (!src || failed === src) return <span className={styles.monogram} style={box} aria-hidden="true">{symbol.slice(0, 2)}</span>;
  return <span className={styles.logo} style={box}>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={src} alt="" width={size - 4} height={size - 4} loading="lazy" referrerPolicy="no-referrer"
      onLoad={event => { if (!registered && event.currentTarget.naturalWidth <= 16) setFailed(src); }} onError={() => setFailed(src)} />
  </span>;
}
