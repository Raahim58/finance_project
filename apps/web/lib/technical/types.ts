export type TechnicalBar = {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    changePercent: number | null;
    source: string;
    sourceUrl?: string | null;
    ingestedAt?: string;
};
export type Values = Array<number | null>;
export type ChartMode = "candles" | "line";
export type LowerIndicator = "none" | "macd" | "rsi" | "roc" | "stochastic";
export type Overlay = "ma20" | "ma50" | "ma200" | "ema20" | "ema50" | "bollinger" | "levels";
export type ChartSettings = {
    mode: ChartMode;
    overlays: Overlay[];
    lower: LowerIndicator;
    volume: boolean;
    volumeMA: boolean;
    signals: boolean;
};
export const defaultSettings: ChartSettings = { mode: "candles", overlays: [], lower: "none", volume: true, volumeMA: false, signals: false };
export type TechnicalSignal = {
    id: string;
    date: string;
    value: number;
    type: "macd_bullish_cross" | "macd_bearish_cross" | "bollinger_upper_break" | "bollinger_lower_break" | "volume_spike" | "resistance_breakout" | "support_breakdown";
    label: string;
    description: string;
    pane: "price" | "volume" | "macd";
};
