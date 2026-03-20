## Context

The Position Engine (Sprint A) can operate in model_assisted mode when a `MarketSignal` is provided, adjusting entry confidence, stop widths, and pyramid behavior based on predicted direction, regime, and volatility. Sprint B provides the Feature Store with raw features. This sprint builds the models that transform features into signals.

The critical architectural constraint: Prediction Engine has **zero knowledge** of positions, PnL, or account state. It is optimized on prediction quality metrics only.

## Goals / Non-Goals

**Goals:**
- Feature pipeline that prepares ML-ready data from the Feature Store
- Direction classifier (LightGBM) with Optuna hyperparameter search
- Regime classifier (HMM) mapping hidden states to market regimes
- Volatility forecaster (GARCH) predicting N-day-ahead volatility
- Signal combiner merging sub-models into `MarketSignal` with staleness checks
- MLflow experiment tracking for reproducibility
- Walk-forward validation to avoid look-ahead bias

**Non-Goals:**
- Deep learning models or transformers — LightGBM + HMM + GARCH is the Phase 1 baseline
- Online/incremental learning — models are retrained periodically offline
- Feature engineering research — use the features Sprint B provides
- Position parameter optimization — Sprint E (sequential optimization Stage 2)

## Decisions

### Package layout

```
quant_engine/
├── prediction/
│   ├── __init__.py
│   ├── features.py       # Feature pipeline (merge, clean, split)
│   ├── direction.py       # LightGBM direction classifier
│   ├── regime.py          # HMM regime classifier
│   ├── volatility.py      # GARCH volatility forecaster
│   ├── combiner.py        # Signal combiner → MarketSignal
│   └── engine.py          # PredictionEngine facade
```

**Rationale:** Each sub-model is a separate module that can be tested, trained, and swapped independently. The `PredictionEngine` facade orchestrates them and exposes the `predict()` / `predict_batch()` interface.

### Sub-model independence

Each sub-model (direction, regime, volatility) has its own `train()` and `predict()` methods and can be trained independently. The combiner calls each one and merges results.

**Rationale:** This allows retraining one model without touching others. It also enables A/B testing of individual sub-models.

### Walk-forward validation for direction classifier

Instead of a single train/val split, the direction classifier uses expanding-window walk-forward validation: train on [0, t], predict [t, t+k], advance, repeat. Final metrics are averaged across folds.

**Rationale:** Time-series data makes random cross-validation invalid. Walk-forward avoids look-ahead bias and tests real deployment conditions.

### HMM state mapping: learned then manually labeled

The HMM trains on returns + volatility + volume features. After training, hidden states are inspected and manually mapped to regime labels based on their characteristic statistics (mean return, volatility level).

**Rationale:** HMM states are unordered — automatic mapping would be fragile. Manual mapping after inspecting state characteristics is standard practice.

### GARCH: arch package with standardized output

The volatility forecaster uses the `arch` package's `GARCH(1,1)` with t-distributed errors. Output is converted from annualized variance to N-day-ahead volatility in price points using the current price level and ATR scaling.

**Rationale:** `arch` is the standard Python GARCH implementation. Converting to price points makes the output directly usable by Position Engine for stop-width suggestions.

### MLflow: local tracking server

Use MLflow with local file store (no remote server). Each training run logs: model type, hyperparameters, metrics, and serialized model artifact.

**Rationale:** Local MLflow is zero-infrastructure. A remote tracking server can be added later if needed.

## Risks / Trade-offs

- **[Risk] Direction classifier may not beat random on TW futures** → Mitigation: Start with basic features, iterate. The system degrades gracefully to rule_only mode when confidence_valid is False.
- **[Risk] HMM regime labels may not be stable across retraining** → Mitigation: Pin state-to-label mapping in config. Alert when retraining produces states with different characteristics.
- **[Risk] GARCH volatility forecast may lag regime shifts** → Mitigation: Use shorter estimation windows and combine with realized vol for robustness.
- **[Risk] Optuna hyperparameter search is expensive** → Mitigation: Cap trials, use early stopping, parallelize with joblib.
