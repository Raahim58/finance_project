"use client";
import ReactECharts from "echarts-for-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getCompanyHistory, getMarketFreshness, type MarketPrice, type MarketFreshness } from "@/lib/api/market";
import { normalizePriceHistory } from "@/lib/technical/normalize";
import { historyRequest, rangeStart, type TechnicalRange } from "@/lib/technical/ranges";
import { supportResistance } from "@/lib/technical/support-resistance";
import { detectSignals } from "@/lib/technical/signals";
import { technicalSeries } from "@/lib/technical/series";
import { defaultSettings } from "@/lib/technical/types";
import { overlayColors, overlayLabels } from "./appearance";
import { chartOptions } from "./chart-options";
import { TechnicalChartToolbar } from "./TechnicalChartToolbar";
import styles from "./technical-chart.module.css";
export function TechnicalChart({ symbol, endDate }: {
    symbol: string;
    endDate?: string;
}) {
    const [range, setRange] = useState<TechnicalRange>("1M"), [settings, setSettings] = useState(defaultSettings);
    const [result, setResult] = useState<{
        key: string;
        rows: MarketPrice[];
        error?: string;
    } | null>(null), [retry, setRetry] = useState(0);
    const [freshness, setFreshness] = useState<MarketFreshness | null>(null);
    const zoom = useRef({ start: 0, end: 100 });
    const chart = useRef<ReactECharts>(null), node = useRef<HTMLDivElement>(null);
    const end = endDate ?? new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Karachi", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    const key = `${symbol}:${range}:${end}:${retry}`;
    useEffect(() => { let active = true; void getCompanyHistory(symbol, 2000, historyRequest(end, range)).then(rows => { if (active)
        setResult({ key, rows }); }).catch(error => { if (active)
        setResult({ key, rows: [], error: error instanceof Error ? error.message : "History request failed" }); }); return () => { active = false; }; }, [symbol, range, end, key]);
    useEffect(() => { let active = true; void getMarketFreshness().then(value => { if (active)
        setFreshness(value); }).catch(() => { if (active)
        setFreshness(null); }); return () => { active = false; }; }, [symbol]);
    const normalized = useMemo(() => normalizePriceHistory(result?.key === key ? result.rows : []), [result, key]);
    const bars = useMemo(() => { const start = rangeStart(end, range); return normalized.bars.filter(bar => !start || bar.date >= start); }, [normalized, end, range]);
    const fullIndicators = useMemo(() => technicalSeries(normalized.bars), [normalized]);
    const indicators = useMemo(() => {
        const offset = normalized.bars.length - bars.length;
        return { ...fullIndicators, ma20: fullIndicators.ma20.slice(offset), ma50: fullIndicators.ma50.slice(offset), ma200: fullIndicators.ma200.slice(offset), ema20: fullIndicators.ema20.slice(offset), ema50: fullIndicators.ema50.slice(offset), volumeMA: fullIndicators.volumeMA.slice(offset), bollinger: { upper: fullIndicators.bollinger.upper.slice(offset), middle: fullIndicators.bollinger.middle.slice(offset), lower: fullIndicators.bollinger.lower.slice(offset) }, macd: { line: fullIndicators.macd.line.slice(offset), signal: fullIndicators.macd.signal.slice(offset), histogram: fullIndicators.macd.histogram.slice(offset) }, rsi: fullIndicators.rsi.slice(offset), roc: fullIndicators.roc.slice(offset), stochastic: { k: fullIndicators.stochastic.k.slice(offset), d: fullIndicators.stochastic.d.slice(offset) } };
    }, [fullIndicators, normalized, bars]);
    const levelHistory = useMemo(() => supportResistance(normalized.bars), [normalized]);
    const fullSignals = useMemo(() => detectSignals(normalized.bars, fullIndicators, levelHistory), [normalized, fullIndicators, levelHistory]);
    const signals = useMemo(() => { const dates = new Set(bars.map(bar => bar.date)); return fullSignals.filter(signal => dates.has(signal.date)); }, [fullSignals, bars]);
    const levels = useMemo(() => { return levelHistory.at(-1) ?? []; }, [levelHistory, normalized, bars]);
    const option = useMemo(() => chartOptions(bars, settings, zoom.current, indicators, signals, levels), [bars, settings, indicators, signals, levels]);
    useEffect(() => { if (!node.current || typeof ResizeObserver === "undefined")
        return; const observer = new ResizeObserver(() => chart.current?.getEchartsInstance().resize()); observer.observe(node.current); return () => observer.disconnect(); }, [bars.length]);
    const events = useMemo(() => ({ datazoom: (event: {
            start?: number;
            end?: number;
            batch?: Array<{
                start: number;
                end: number;
            }>;
        }) => { const value = event.batch?.[0] ?? event; if (value.start != null && value.end != null)
            zoom.current = { start: value.start, end: value.end }; } }), []);
    const latest = bars.at(-1), loading = result?.key !== key;
    return <section className={styles.canvas} aria-label={`${symbol} technical chart`}><div className={styles.heading}><h2>{symbol} · Price history</h2><span>Daily · PKR{latest ? ` · ${latest.close.toFixed(2)}${latest.changePercent == null ? "" : ` (${latest.changePercent.toFixed(2)}%)`}` : ""}</span></div>
    <TechnicalChartToolbar range={range} onRange={value => { setRange(value); zoom.current = { start: 0, end: 100 }; }} settings={settings} onSettings={setSettings} onReset={() => { zoom.current = { start: 0, end: 100 }; chart.current?.getEchartsInstance().dispatchAction({ type: "dataZoom", start: 0, end: 100 }); }}/>
    {settings.overlays.length > 0 ? <div className={styles.unavailable} aria-label="Active price overlays">{settings.overlays.map(key => <span key={key} style={{ color: overlayColors[key] }}>{overlayLabels[key]}</span>)}</div> : null}
    {loading ? <p className={styles.status} role="status">Loading daily history…</p> : result?.error ? <p className={styles.status} role="alert">History unavailable: {result.error} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p> : !bars.length ? <p className={styles.status}>No valid daily OHLCV observations in this range. Select a longer range.</p> : <div ref={node} role="img" aria-label={`${symbol} daily price${settings.volume ? " and volume" : ""}, ${bars[0].date} to ${latest!.date}`}><ReactECharts ref={chart} option={option} notMerge lazyUpdate onEvents={events} style={{ height: settings.lower === "none" ? 480 : 600, width: "100%" }}/></div>}
    {bars.length ? <div className={styles.unavailable}>{settings.overlays.filter(key => key !== "levels").map(key => { const values = key === "bollinger" ? indicators.bollinger.upper : indicators[key as "ma20" | "ma50" | "ma200" | "ema20" | "ema50"]; return values.every(value => value == null) ? <span key={key}>{key.toUpperCase()} unavailable: insufficient history</span> : null; })}{settings.lower !== "none" && (settings.lower === "macd" ? indicators.macd.signal : settings.lower === "stochastic" ? indicators.stochastic.d : indicators[settings.lower]).every(value => value == null) ? <span>{settings.lower.toUpperCase()} unavailable: insufficient history</span> : null}{settings.volume && settings.volumeMA && indicators.volumeMA.every(value => value == null) ? <span>Volume MA20 unavailable: insufficient history</span> : null}</div> : null}
    {settings.overlays.includes("levels") && bars.length && !levels.length ? <p className={styles.caption}>No nearby pivot clusters with at least two confirmed touches.</p> : null}
    {settings.overlays.includes("levels") && levels.length > 0 ? <p className={styles.caption}>Current pivot clusters: {levels.map(level => `PKR ${level.value.toFixed(2)} (${level.touches} touches)`).join(" · ")}. Lines show current levels; crossing events use levels established before their session.</p> : null}
    {settings.signals ? <p className={styles.caption}>Markers show crossings for visible indicators, with the latest 12 events per pane displayed. Events describe observations, not investment recommendations.</p> : null}
    {latest && /mock|demo|synthetic/i.test(bars.map(bar => bar.source).join(" ")) ? <p className={styles.warning}>This history includes demo or synthetic observations, as labelled by its sources.</p> : null}
    {latest && freshness?.latest_trade_date && latest.date < freshness.latest_trade_date ? <p className={styles.warning}>This security’s last daily observation ({latest.date}) precedes the market’s latest session ({freshness.latest_trade_date}).</p> : null}
    {latest && range !== "MAX" && normalized.bars[0].date > rangeStart(end, range)! ? <p className={styles.caption}>Available observations begin on {bars[0].date}; coverage of the full requested period is not established.</p> : null}
    {!loading && normalized.rejected > 0 ? <p className={styles.warning}>{normalized.rejected} invalid or duplicate observations excluded; missing sessions are not interpolated.</p> : null}
    {freshness?.is_stale ? <p className={styles.warning}>{freshness.stale_warning ?? "Market data is stale."}</p> : null}
    {latest ? <p className={styles.caption}>{bars.length} displayed sessions · {bars[0].date}–{latest.date} · Sources: {[...new Set(bars.map(bar => bar.source))].join(", ")}{latest.sourceUrl ? <> · <a href={latest.sourceUrl} target="_blank" rel="noreferrer">Latest source ↗</a></> : null} · Daily observations only. {freshness ? freshness.exchange_session_note : "Market freshness status unavailable."}{result?.rows.length === 2000 ? " History capped at 2,000 observations." : ""}</p> : null}
  </section>;
}
