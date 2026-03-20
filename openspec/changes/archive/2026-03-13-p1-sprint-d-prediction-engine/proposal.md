## Why

Sprints A–C provide the Position Engine, data pipeline, and backtester, but the engine runs in rule_only mode without a prediction model. The Prediction Engine transforms raw features into `MarketSignal`, enabling model_assisted mode with adaptive entries, regime-aware behavior, and volatility-adjusted stops. This is the intelligence layer that differentiates the platform from a static rule-based system.

## What Changes

- Implement feature engineering pipeline: merge Feature Store output into ML-ready DataFrame, handle missing values, train/val/OOS split
- Implement LightGBM direction classifier with Optuna hyperparameter search and walk-forward validation
- Implement HMM regime classifier (3–4 hidden states mapped to market regimes)
- Implement GARCH(1,1) volatility forecaster
- Implement signal combiner: merge sub-model outputs into `MarketSignal`, with staleness validation and version tagging
- Set up MLflow experiment tracking

## Capabilities

### New Capabilities

_(none — prediction-engine capability already has a spec)_

### Modified Capabilities

- `prediction-engine`: Implement from existing spec — direction classifier, regime classifier, volatility forecaster, signal combiner, experiment tracking

## Impact

- **New packages**: `quant_engine.prediction.features`, `quant_engine.prediction.direction`, `quant_engine.prediction.regime`, `quant_engine.prediction.volatility`, `quant_engine.prediction.combiner`
- **Dependencies**: lightgbm, optuna, hmmlearn, arch, mlflow, scikit-learn
- **Consumes**: Feature Store (Sprint B) for training data, Backtester (Sprint C) for walk-forward validation
- **Downstream unblocked**: Sprint E can wire Prediction → Position in model_assisted mode and run sequential optimization
