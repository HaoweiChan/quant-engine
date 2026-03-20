## 1. Feature Pipeline (`quant_engine/prediction/features.py`)

- [x] 1.1 Implement feature merge: combine Feature Store output into a single ML-ready DataFrame keyed by timestamp — acceptance: all indicator columns + market-specific columns present
- [x] 1.2 Implement NaN/inf handling: forward-fill then drop remaining NaN rows, log affected columns — acceptance: no NaN/inf in output DataFrame
- [x] 1.3 Implement time-ordered data split: 60% train / 15% model val / 15% position train+val / 10% final OOS — acceptance: splits are strictly chronological with no overlap
- [x] 1.4 Implement feature importance computation via LightGBM built-in importance — acceptance: ranked feature list stored alongside model

## 2. Direction Classifier (`quant_engine/prediction/direction.py`)

- [x] 2.1 Implement LightGBM binary classifier: predict up/down over configurable N-day horizon — acceptance: outputs probability in [0, 1]
- [x] 2.2 Implement direction/confidence mapping: probability → direction in [-1, +1] and direction_conf in [0, 1] — acceptance: strong probability maps to high confidence
- [x] 2.3 Implement Optuna hyperparameter search: Bayesian optimization targeting accuracy and Brier score — acceptance: best params stored, trial history logged
- [x] 2.4 Implement walk-forward validation: expanding window with configurable step size — acceptance: per-fold and aggregated metrics computed, no look-ahead
- [x] 2.5 Implement evaluation metrics: accuracy, precision, recall, Brier score, AUC — acceptance: all metrics computed on validation folds
- [x] 2.6 Implement model serialization: save/load trained model — acceptance: loaded model produces identical predictions

## 3. Regime Classifier (`quant_engine/prediction/regime.py`)

- [x] 3.1 Implement HMM with 3–4 hidden states using hmmlearn: input features are returns, volatility, volume — acceptance: model trains without errors, states assigned to each observation
- [x] 3.2 Implement state-to-regime mapping: map hidden states to {trending, choppy, volatile, uncertain} based on state statistics — acceptance: mapping stored in config, reproducible
- [x] 3.3 Implement regime stability evaluation: measure average state duration, flag rapid switching — acceptance: report includes mean state duration and switching frequency
- [x] 3.4 Implement trend_strength output: derived from state posterior probability — acceptance: value in [0, 1], high when model is confident about current state

## 4. Volatility Forecaster (`quant_engine/prediction/volatility.py`)

- [x] 4.1 Implement GARCH(1,1) with t-distributed errors via arch package: input is daily returns — acceptance: model fits without convergence errors
- [x] 4.2 Implement N-day ahead volatility forecast: convert annualized variance to price-point volatility — acceptance: output is positive float in reasonable range
- [x] 4.3 Implement forecast validation: compare against realized volatility on validation set — acceptance: forecast tracks realized vol with reasonable MAE

## 5. Signal Combiner (`quant_engine/prediction/combiner.py`)

- [x] 5.1 Implement combiner: merge direction, regime, volatility outputs into a single MarketSignal — acceptance: all MarketSignal fields populated with valid values
- [x] 5.2 Implement staleness check: if any sub-model hasn't updated within its freshness window → set confidence_valid=False — acceptance: stale sub-model invalidates signal
- [x] 5.3 Implement version tagging: model_version reflects current model artifact version — acceptance: version string includes sub-model versions
- [x] 5.4 Implement suggested parameter hints: optionally set suggested_stop_atr_mult and suggested_add_atr_mult based on vol_forecast — acceptance: hints populated when vol forecast is confident

## 6. Prediction Engine Facade (`quant_engine/prediction/engine.py`)

- [x] 6.1 Implement PredictionEngine class: orchestrates feature pipeline → sub-models → combiner — acceptance: `predict()` returns valid MarketSignal from raw features
- [x] 6.2 Implement `predict_batch()`: efficient batch prediction for backtesting — acceptance: returns N signals for N-row DataFrame, timestamp-aligned
- [x] 6.3 Implement `get_model_info()`: return model versions, training dates, key metrics — acceptance: dict contains required fields
- [x] 6.4 Verify zero-knowledge constraint: PredictionEngine module has no imports from position_engine, risk_monitor, or execution — acceptance: import check passes

## 7. MLflow Integration

- [x] 7.1 Set up MLflow local tracking with file store — acceptance: tracking URI configured, UI accessible
- [x] 7.2 Log training runs for direction classifier: params, metrics, model artifact — acceptance: runs visible in MLflow UI
- [x] 7.3 Log training runs for regime classifier and volatility forecaster — acceptance: all sub-model runs tracked

## 8. Tests

- [x] 8.1 Feature pipeline tests: verify merge, NaN handling, split correctness (no temporal leakage) — acceptance: splits are chronological, no NaN in output
- [x] 8.2 Direction classifier tests: train on synthetic data, verify output ranges, verify walk-forward produces valid folds — acceptance: direction in [-1,1], conf in [0,1]
- [x] 8.3 Regime classifier tests: train on synthetic regime-switching data, verify state mapping produces valid labels — acceptance: regime in allowed set
- [x] 8.4 Volatility forecaster tests: train on synthetic GARCH data, verify positive forecast — acceptance: forecast > 0
- [x] 8.5 Combiner tests: verify signal assembly, verify staleness invalidation — acceptance: stale sub-model → confidence_valid=False
- [x] 8.6 Integration test: features → predict() → valid MarketSignal — acceptance: end-to-end pipeline works
- [x] 8.7 Zero-knowledge test: verify prediction module has no forbidden imports — acceptance: static import check passes

## 9. Quality Gates

- [x] 9.1 `ruff check` passes with zero errors
- [x] 9.2 `mypy --strict` passes with zero errors
- [x] 9.3 All pytest tests pass
