import { useEffect, useId, useRef } from "react";
import type { ChartSettings, Overlay, LowerIndicator } from "@/lib/technical/types";
import styles from "./technical-chart.module.css";
const overlays: Array<[
    Overlay,
    string
]> = [["ma20", "MA20"], ["ma50", "MA50"], ["ma200", "MA200"], ["ema20", "EMA20"], ["ema50", "EMA50"], ["bollinger", "Bollinger Bands (20, 2)"], ["levels", "Support / Resistance"]];
const lower: Array<[
    LowerIndicator,
    string
]> = [["none", "None"], ["macd", "MACD (12, 26, 9)"], ["rsi", "RSI (14)"], ["roc", "ROC (12)"], ["stochastic", "Stochastic (14, 3, 3)"]];
export function IndicatorMenu({ settings, onChange }: {
    settings: ChartSettings;
    onChange: (settings: ChartSettings) => void;
}) {
    const menu = useRef<HTMLDetailsElement>(null), groupId = useId();
    useEffect(() => { const close = (event: PointerEvent) => { if (menu.current && !menu.current.contains(event.target as Node))
        menu.current.open = false; }; document.addEventListener("pointerdown", close); return () => document.removeEventListener("pointerdown", close); }, []);
    return <details ref={menu} className={styles.menu} onKeyDown={event => { if (event.key === "Escape")
        event.currentTarget.open = false; }}><summary>Indicators ▾</summary><div className={styles.choices}>
    <fieldset><legend>Price</legend>{overlays.map(([key, label]) => <label key={key}><input type="checkbox" checked={settings.overlays.includes(key)} onChange={event => onChange({ ...settings, overlays: event.target.checked ? [...settings.overlays, key] : settings.overlays.filter(value => value !== key) })}/>{label}</label>)}</fieldset>
    <fieldset><legend>Lower pane</legend>{lower.map(([key, label]) => <label key={key}><input type="radio" name={groupId} checked={settings.lower === key} onChange={() => onChange({ ...settings, lower: key })}/>{label}</label>)}</fieldset>
    <fieldset><legend>Volume</legend><label><input type="checkbox" checked={settings.volume} onChange={event => onChange({ ...settings, volume: event.target.checked })}/>Volume</label><label><input type="checkbox" checked={settings.volumeMA} onChange={event => onChange({ ...settings, volumeMA: event.target.checked, volume: event.target.checked || settings.volume })}/>Volume MA20</label></fieldset>
    <fieldset><legend>Signals</legend><label><input type="checkbox" checked={settings.signals} onChange={event => onChange({ ...settings, signals: event.target.checked })}/>Show technical signals</label></fieldset>
  </div></details>;
}
