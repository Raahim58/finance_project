"use client";

import { useEffect, useState } from "react";
import { getCompanyHistory } from "@/lib/api";
import { numeric } from "@/lib/overview";

export function SparkPath({ values, width = 64, height = 22 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span aria-label="No trend data" style={{ color: "#a7a79d", fontSize: 11 }}>—</span>;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1) * width).toFixed(1)},${(height - 2 - (value - min) / span * (height - 4)).toFixed(1)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${values.length} recent closes, ${up ? "higher" : "lower"} overall`}>
    <polyline points={points} fill="none" stroke={up ? "#176044" : "#b44d41"} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}

// Recent stored daily closes for one symbol (no intraday series exists).
export function CompanyTrend({ symbol }: { symbol: string }) {
  const [values, setValues] = useState<number[] | null>(null);
  useEffect(() => {
    let active = true;
    getCompanyHistory(symbol, 30).then(rows => { if (active) setValues(rows.flatMap(row => { const close = numeric(row.close); return close == null ? [] : [close]; })); }).catch(() => { if (active) setValues([]); });
    return () => { active = false; };
  }, [symbol]);
  return values ? <SparkPath values={values} /> : <span style={{ display: "inline-block", width: 64, height: 22 }} />;
}
