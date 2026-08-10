from __future__ import annotations

from datetime import date

import numpy as np


def market_model_event_study(
    dates: list[date],
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    event_dates: list[date],
    *,
    estimation_window: int = 120,
    estimation_gap: int = 20,
    pre_sessions: int = 5,
    post_sessions: int = 5,
) -> dict[str, object]:
    asset = np.asarray(asset_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if len(dates) != asset.size or asset.shape != benchmark.shape:
        raise ValueError("Dates and aligned returns must have equal lengths")
    if not np.all(np.isfinite(asset)) or not np.all(np.isfinite(benchmark)):
        raise ValueError("Event-study returns must be finite")
    results = []
    used_windows: list[tuple[int, int]] = []
    for requested in sorted(set(event_dates)):
        event_index = next((index for index, day in enumerate(dates) if day >= requested), None)
        if event_index is None:
            results.append({"requested_event_date": requested, "available": False, "reason": "No trading session on or after event date"})
            continue
        estimation_end = event_index - estimation_gap
        estimation_start = estimation_end - estimation_window
        window_start = event_index - pre_sessions
        window_end = event_index + post_sessions + 1
        if estimation_start < 0 or window_start < 0 or window_end > asset.size:
            results.append({"requested_event_date": requested, "event_session": dates[event_index], "available": False, "reason": "Insufficient estimation or event-window observations"})
            continue
        x = benchmark[estimation_start:estimation_end]
        y = asset[estimation_start:estimation_end]
        design = np.column_stack([np.ones(x.size), x])
        alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
        event_asset = asset[window_start:window_end]
        event_market = benchmark[window_start:window_end]
        abnormal = event_asset - (alpha + beta * event_market)
        overlap = any(not (window_end <= start or window_start >= end) for start, end in used_windows)
        used_windows.append((window_start, window_end))
        results.append({
            "requested_event_date": requested,
            "event_session": dates[event_index],
            "available": True,
            "estimation_start": dates[estimation_start],
            "estimation_end": dates[estimation_end - 1],
            "estimation_sample_size": int(x.size),
            "alpha_daily": float(alpha),
            "beta": float(beta),
            "event_window": [dates[window_start], dates[window_end - 1]],
            "abnormal_returns": [{"date": dates[index], "value": float(abnormal[index - window_start])} for index in range(window_start, window_end)],
            "cumulative_abnormal_return": float(np.sum(abnormal)),
            "overlaps_another_event_window": overlap,
        })
    available = [result for result in results if result.get("available")]
    return {
        "events": results,
        "available_event_count": len(available),
        "mean_cumulative_abnormal_return": float(np.mean([result["cumulative_abnormal_return"] for result in available])) if available else None,
        "limitations": ["Market-model OLS is estimated only from sessions before each event.", "Overlapping event windows are flagged and are not statistically independent.", "No causal claim is made."],
    }
