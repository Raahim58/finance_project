from datetime import date, timedelta

import numpy as np
import pytest

from app.domain.quant.event_study import market_model_event_study


def test_event_study_uses_pre_event_estimation_and_flags_overlap():
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(220)]
    market = np.linspace(-0.01, 0.01, 220)
    asset = 0.0001 + 1.2 * market
    asset[180] += 0.05
    result = market_model_event_study(dates, asset, market, [dates[180], dates[182]], estimation_window=120, estimation_gap=20, pre_sessions=2, post_sessions=2)
    first, second = result["events"]
    assert first["available"] is True
    assert first["beta"] == pytest.approx(1.2)
    assert first["cumulative_abnormal_return"] == pytest.approx(0.05)
    assert second["overlaps_another_event_window"] is True
