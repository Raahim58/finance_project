import type { TechnicalBar } from "./types";
import { sma } from "./moving-average";
import { ema } from "./ema";
import { bollinger } from "./bollinger";
import { macd } from "./macd";
import { rsi } from "./rsi";
import { roc } from "./roc";
import { stochastic } from "./stochastic";
export function technicalSeries(bars: TechnicalBar[]) {
    const closes = bars.map(bar => bar.close);
    return { ma20: sma(closes, 20), ma50: sma(closes, 50), ma200: sma(closes, 200), ema20: ema(closes, 20), ema50: ema(closes, 50), bollinger: bollinger(closes), volumeMA: sma(bars.map(bar => bar.volume), 20), macd: macd(closes), rsi: rsi(closes), roc: roc(closes), stochastic: stochastic(bars) };
}
export type TechnicalSeries = ReturnType<typeof technicalSeries>;
