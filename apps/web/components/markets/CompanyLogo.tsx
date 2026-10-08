"use client";

import { useState } from "react";
import { API_BASE_URL } from "@/lib/api/client";
import styles from "./markets.module.css";

// Logos come from the company's own stored website. A missing site or a failed/placeholder
// image falls back to a symbol monogram rather than a made-up mark.
export function CompanyLogo({ symbol, website, size = 26 }: { symbol: string; website?: string | null; size?: number }) {
  const src = `${API_BASE_URL}/market/company/${encodeURIComponent(symbol)}/logo`;
  const [failed, setFailed] = useState<string | null>(null);
  const box = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  if (!src || failed === src) return <span className={styles.monogram} style={box} aria-hidden="true">{symbol.slice(0, 2)}</span>;
  return <span className={styles.logo} style={box}>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={src} alt="" width={size - 4} height={size - 4} loading="lazy" referrerPolicy="no-referrer"
      onError={() => setFailed(src)} />
  </span>;
}
