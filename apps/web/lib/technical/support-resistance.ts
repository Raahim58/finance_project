import type { TechnicalBar } from "./types";
export const levelDefaults = { pivotRadius: 3, clusterFraction: .01, minTouches: 2, lookback: 252, maxLevels: 4, maxDistanceFraction: .2 };
export type PriceLevel = {
    id: string;
    value: number;
    touches: number;
    establishedIndex: number;
    lastTouchIndex: number;
    score: number;
};
type Pivot = {
    index: number;
    confirmed: number;
    value: number;
    significance: number;
};
// Each snapshot uses only pivots confirmed by that session. Never backdate a level.
export function supportResistance(bars: TechnicalBar[], config = levelDefaults): PriceLevel[][] {
    const pivots: Pivot[] = [];
    const radius = config.pivotRadius;
    return bars.map((bar, t) => {
        const i = t - radius;
        if (i >= radius) {
            const candidate = bars[i], neighbors = bars.slice(i - radius, i + radius + 1).filter((_, j) => j !== radius);
            if (neighbors.every(b => candidate.high > b.high))
                pivots.push({ index: i, confirmed: t, value: candidate.high, significance: (candidate.high - Math.min(...neighbors.map(b => b.low))) / candidate.high });
            if (neighbors.every(b => candidate.low < b.low))
                pivots.push({ index: i, confirmed: t, value: candidate.low, significance: (Math.max(...neighbors.map(b => b.high)) - candidate.low) / candidate.low });
        }
        const clusters: Array<{
            pivots: Pivot[];
            value: number;
        }> = [];
        for (const pivot of pivots.filter(p => p.index >= t - config.lookback)) {
            const cluster = clusters.find(c => Math.abs(pivot.value - c.value) / c.value <= config.clusterFraction);
            if (cluster) {
                if (cluster.pivots.some(p => p.index === pivot.index))
                    continue;
                cluster.pivots.push(pivot);
                cluster.value = cluster.pivots.reduce((sum, p) => sum + p.value, 0) / cluster.pivots.length;
            }
            else
                clusters.push({ pivots: [pivot], value: pivot.value });
        }
        return clusters.filter(c => c.pivots.length >= config.minTouches && Math.abs(c.value - bar.close) / bar.close <= config.maxDistanceFraction).map(c => {
            const last = c.pivots.at(-1)!;
            return { id: `level-${c.pivots[0].index}-${c.pivots[0].value}`, value: c.value, touches: c.pivots.length, establishedIndex: c.pivots[config.minTouches - 1].confirmed, lastTouchIndex: last.index, score: c.pivots.length * 2 + Math.max(0, 1 - (t - last.index) / config.lookback) + c.pivots.reduce((sum, p) => sum + p.significance, 0) };
        }).sort((a, b) => b.score - a.score || a.value - b.value).slice(0, config.maxLevels);
    });
}
