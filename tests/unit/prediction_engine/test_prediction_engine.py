"""Integration tests for PredictionEngine + zero-knowledge constraint check."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.prediction.direction import DirectionClassifier
from src.prediction.engine import PredictionEngine
from src.prediction.regime import RegimeClassifier
from src.prediction.volatility import VolatilityForecaster


def _build_trained_engine() -> tuple[PredictionEngine, list[str]]:
    """Build a PredictionEngine with trained sub-models on synthetic data."""
    rng = np.random.default_rng(42)
    n = 500
    feature_cols = ["f1", "f2", "f3", "f4", "f5"]

    # Direction training data
    x_dir = rng.standard_normal((n, len(feature_cols)))
    y_dir = (0.5 * x_dir[:, 0] + 0.3 * x_dir[:, 1] + rng.standard_normal(n) * 0.5 > 0).astype(float)
    direction = DirectionClassifier()
    direction.train(x_dir[:400], y_dir[:400], feature_names=feature_cols)

    # Regime training data
    regime_data = rng.standard_normal((n, 3))
    regime = RegimeClassifier(n_states=3)
    regime.train(regime_data)

    # Volatility training data
    returns = np.zeros(n)
    sigma = np.zeros(n)
    sigma[0] = 0.01
    for t in range(1, n):
        sigma[t] = np.sqrt(0.00001 + 0.1 * returns[t - 1] ** 2 + 0.85 * sigma[t - 1] ** 2)
        returns[t] = sigma[t] * rng.standard_normal()
    vol = VolatilityForecaster(horizon=5)
    vol.train(returns)

    engine = PredictionEngine(
        direction=direction,
        regime=regime,
        volatility=vol,
        feature_cols=feature_cols,
        regime_feature_cols=["f1", "f2", "f3"],
    )
    return engine, feature_cols


def _make_feature_df(feature_cols: list[str], n: int = 10) -> pl.DataFrame:
    rng = np.random.default_rng(99)
    data: dict[str, list[float]] = {col: rng.standard_normal(n).tolist() for col in feature_cols}
    data["timestamp"] = [float(i) for i in range(n)]
    return pl.DataFrame(data)


class TestPredictionEngine:
    def test_predict_returns_valid_signal(self) -> None:
        engine, feature_cols = _build_trained_engine()
        features = _make_feature_df(feature_cols)
        signal = engine.predict(features, current_price=20000.0, atr_daily=150.0)
        assert -1.0 <= signal.direction <= 1.0
        assert 0.0 <= signal.direction_conf <= 1.0
        assert signal.regime in {"trending", "choppy", "volatile", "uncertain"}
        assert 0.0 <= signal.trend_strength <= 1.0

    def test_predict_batch_returns_n_signals(self) -> None:
        engine, feature_cols = _build_trained_engine()
        n = 10
        features = _make_feature_df(feature_cols, n=n)
        prices = pl.Series("price", [20000.0 + i * 10 for i in range(n)])
        signals = engine.predict_batch(features, prices)
        assert len(signals) == n
        for s in signals:
            assert -1.0 <= s.direction <= 1.0
            assert 0.0 <= s.direction_conf <= 1.0

    def test_get_model_info(self) -> None:
        engine, feature_cols = _build_trained_engine()
        info = engine.get_model_info()
        assert "direction_version" in info
        assert "regime_version" in info
        assert "volatility_version" in info
        assert info["feature_cols"] == feature_cols

    def test_fallback_on_empty_features(self) -> None:
        engine, _ = _build_trained_engine()
        empty_df = pl.DataFrame({"timestamp": [], "f1": []}).cast({"f1": pl.Float64})
        signal = engine.predict(empty_df, current_price=20000.0)
        assert signal.confidence_valid is False
        assert signal.model_version == "fallback"

    def test_set_versions(self) -> None:
        engine, _ = _build_trained_engine()
        engine.set_versions(direction="d-v2", regime="r-v2", volatility="vol-v2")
        info = engine.get_model_info()
        assert info["direction_version"] == "d-v2"
        assert info["regime_version"] == "r-v2"
        assert info["volatility_version"] == "vol-v2"


class TestZeroKnowledgeConstraint:
    """Verify prediction module has no imports from position_engine, risk_monitor, or execution."""

    FORBIDDEN_MODULES = {"position_engine", "risk_monitor", "execution", "risk", "simulator"}

    def test_no_forbidden_imports_static(self) -> None:
        prediction_dir = Path(__file__).parent.parent.parent.parent / "src" / "prediction"
        for py_file in prediction_dir.glob("*.py"):
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._check_import(alias.name, py_file.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._check_import(node.module, py_file.name)

    def _check_import(self, module_name: str, file_name: str) -> None:
        parts = module_name.split(".")
        for forbidden in self.FORBIDDEN_MODULES:
            if forbidden in parts:
                pytest.fail(
                    f"{file_name} imports forbidden module '{module_name}' "
                    f"(contains '{forbidden}')"
                )

    def test_no_forbidden_runtime_imports(self) -> None:
        import src.prediction.combiner as comb_mod
        import src.prediction.direction as dir_mod
        import src.prediction.engine as eng_mod
        import src.prediction.features as feat_mod
        import src.prediction.regime as reg_mod
        import src.prediction.volatility as vol_mod

        for mod in [eng_mod, feat_mod, dir_mod, reg_mod, vol_mod, comb_mod]:
            source = inspect.getsource(mod)
            for forbidden in self.FORBIDDEN_MODULES:
                # Check for "from src.<forbidden>" or "import src.<forbidden>"
                assert f"src.{forbidden}" not in source, (
                    f"{mod.__name__} references src.{forbidden}"
                )
