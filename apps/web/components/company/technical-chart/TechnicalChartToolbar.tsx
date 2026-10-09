import { technicalRanges, type TechnicalRange } from "@/lib/technical/ranges";
import type { ChartSettings } from "@/lib/technical/types";
import { IndicatorMenu } from "./IndicatorMenu";
import styles from "./technical-chart.module.css";
export function TechnicalChartToolbar({ range, onRange, settings, onSettings, onReset }: {
    range: TechnicalRange;
    onRange: (range: TechnicalRange) => void;
    settings: ChartSettings;
    onSettings: (settings: ChartSettings) => void;
    onReset: () => void;
}) {
    return <div className={styles.toolbar}><div className={styles.group} role="group" aria-label="Technical chart range">{technicalRanges.map(value => <button key={value} aria-pressed={range === value} onClick={() => onRange(value)}>{value}</button>)}</div><div className={styles.group} role="group" aria-label="Chart controls">{(["candles", "line"] as const).map(mode => <button key={mode} aria-pressed={settings.mode === mode} onClick={() => onSettings({ ...settings, mode })}>{mode === "candles" ? "Candles" : "Line"}</button>)}<IndicatorMenu settings={settings} onChange={onSettings}/><button onClick={onReset}>Reset zoom</button></div></div>;
}
