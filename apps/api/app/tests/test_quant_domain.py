import numpy as np
import pytest

from app.domain.quant.estimators import estimate_expected_returns
from app.domain.quant.metrics import covariance_matrix, risk_metrics
from app.domain.quant.optimizer import optimize


def test_covariance_shrinkage_is_symmetric_and_psd():
    returns = np.array([[0.01, 0.02], [-0.01, 0.005], [0.02, -0.01], [0.003, 0.004]])
    covariance = covariance_matrix(returns, shrinkage=0.20)
    assert np.allclose(covariance, covariance.T)
    assert np.min(np.linalg.eigvalsh(covariance)) >= -1e-12


def test_minimum_variance_requires_no_expected_return_estimator():
    covariance = np.array([[0.04, 0.0], [0.0, 0.01]])
    result = optimize(covariance)
    assert result.status == "optimal"
    assert sum(result.weights) == pytest.approx(1)
    assert result.weights[1] > result.weights[0]
    assert result.expected_return is None


def test_expected_returns_are_pluggable_and_user_model_is_explicit():
    returns = np.array([[0.01, 0.02], [0.0, 0.01], [-0.01, 0.005]])
    historical = estimate_expected_returns("historical_shrunk", returns, shrinkage=0.5)
    assumed = estimate_expected_returns("user_model", returns, assumptions=[0.12, 0.08])
    assert historical.method == "historical_shrunk"
    assert assumed.values.tolist() == [0.12, 0.08]
    with pytest.raises(ValueError, match="one explicit assumption"):
        estimate_expected_returns("user_model", returns, assumptions=[0.12])


def test_risk_metrics_drawdown_and_tail_loss_conventions():
    result = risk_metrics([0.10, -0.20, 0.05, -0.01])
    assert result.max_drawdown <= 0
    assert result.historical_var_95 > 0
    assert result.historical_es_95 >= result.historical_var_95
