## Purpose

Generate market predictions from feature data, outputting a standardized MarketSignal. Combines a LightGBM direction classifier, HMM regime classifier, and GARCH volatility forecaster. Optimized on prediction-quality metrics only — never on PnL.

## Requirements

### Requirement: Prediction Engine interface
Prediction Engine SHALL expose `predict()` and `predict_batch()` methods that produce `MarketSignal` from feature data.

```python
class PredictionEngine:
    def predict(self, features: pd.DataFrame) -> MarketSignal: ...
    def predict_batch(self, features: pd.DataFrame) -> list[MarketSignal]: ...
    def get_model_info(self) -> dict: ...
```

#### Scenario: Single prediction
- **WHEN** `predict()` is called with a single-row feature DataFrame
- **THEN** it SHALL return a fully populated `MarketSignal` with valid ranges for all fields

#### Scenario: Batch prediction for backtesting
- **WHEN** `predict_batch()` is called with an N-row feature DataFrame
- **THEN** it SHALL return a list of N `MarketSignal` objects, one per row, preserving timestamp alignment

#### Scenario: Model info
- **WHEN** `get_model_info()` is called
- **THEN** it SHALL return a dict containing at least `model_version`, `training_date`, and key performance metrics

### Requirement: Zero knowledge of positions
Prediction Engine SHALL have zero knowledge of current positions, account PnL, margin status, or any Position Engine state. It operates on features only.

#### Scenario: No position imports
- **WHEN** the Prediction Engine module is loaded
- **THEN** it SHALL NOT import from `core.position_engine`, `core.risk_monitor`, or any execution module

#### Scenario: Features only
- **WHEN** `predict()` is called
- **THEN** the input DataFrame SHALL contain only market data features (price, volume, indicators) — never position, PnL, or account fields

### Requirement: Direction classifier
Prediction Engine SHALL include a LightGBM-based binary direction classifier that predicts up/down movement over a configurable horizon.

#### Scenario: Output direction and confidence
- **WHEN** the direction classifier runs
- **THEN** it SHALL output `direction` in `[-1.0, +1.0]` and `direction_conf` in `[0.0, 1.0]`

#### Scenario: Optimized on prediction metrics only
- **WHEN** the direction classifier is trained
- **THEN** optimization SHALL target accuracy, Brier score, and AUC — never PnL-based metrics

#### Scenario: Hyperparameter search
- **WHEN** training the direction classifier
- **THEN** hyperparameters SHALL be optimized via Bayesian search (Optuna) with walk-forward validation

### Requirement: Regime classifier
Prediction Engine SHALL include an HMM-based regime classifier that categorizes current market state.

#### Scenario: Output regime label
- **WHEN** the regime classifier runs
- **THEN** it SHALL output a `regime` string from `{"trending", "choppy", "volatile", "uncertain"}` and `trend_strength` in `[0.0, 1.0]`

#### Scenario: Regime stability
- **WHEN** market conditions are stable
- **THEN** the regime classifier SHALL NOT switch states on every bar — rapid switching indicates a modeling problem

#### Scenario: HMM hidden states
- **WHEN** the HMM is trained
- **THEN** it SHALL use 3 or 4 hidden states mapped to the four regime labels

### Requirement: Volatility forecaster
Prediction Engine SHALL include a GARCH(1,1)-based volatility forecaster that predicts N-day-ahead volatility.

#### Scenario: Output vol_forecast
- **WHEN** the volatility forecaster runs
- **THEN** it SHALL output `vol_forecast` as a positive float representing predicted N-day volatility in price points

#### Scenario: Reasonable forecast range
- **WHEN** `vol_forecast` is produced
- **THEN** it SHALL be positive and bounded by historical observed volatility ranges (not produce extreme outliers)

### Requirement: Signal combiner
Prediction Engine SHALL combine sub-model outputs (direction, regime, volatility) into a single `MarketSignal`.

#### Scenario: Merge sub-model outputs
- **WHEN** all sub-models have produced their outputs
- **THEN** the combiner SHALL merge them into one `MarketSignal` with all fields populated

#### Scenario: Staleness invalidation
- **WHEN** any sub-model has not updated within its expected freshness window
- **THEN** the combiner SHALL set `confidence_valid = False` on the output signal

#### Scenario: Version tagging
- **WHEN** a signal is produced
- **THEN** `model_version` SHALL reflect the current model artifact version

### Requirement: Sequential optimization protocol
Prediction Engine parameters SHALL be optimized in Stage 1 of the sequential protocol — on prediction-quality metrics only, before Position Engine optimization.

#### Scenario: Stage 1 optimization
- **WHEN** the prediction models are optimized
- **THEN** optimization SHALL use the model validation split (15% of data) and target prediction metrics (accuracy, Brier, AUC)

#### Scenario: Data split compliance
- **WHEN** training and evaluating prediction models
- **THEN** the data split SHALL be: 60% train, 15% model validation, 15% position train+val, 10% final OOS — with no temporal leakage (strictly time-ordered, no shuffling)

### Requirement: Experiment tracking
Prediction Engine SHALL log all training runs, parameters, and metrics to MLflow.

#### Scenario: MLflow logging
- **WHEN** a model training run completes
- **THEN** it SHALL log parameters, metrics, and model artifacts to MLflow for reproducibility

### Requirement: Feature pipeline
Prediction Engine SHALL include a feature pipeline that transforms Feature Store output into ML-ready DataFrames.

#### Scenario: NaN/inf handling
- **WHEN** the feature pipeline processes raw features
- **THEN** it SHALL replace NaN and inf values with appropriate defaults or forward-fills, and log which columns had missing data

#### Scenario: Time-ordered split
- **WHEN** the feature pipeline splits data for training
- **THEN** it SHALL use strictly time-ordered splits (60% train, 15% model val, 15% position train+val, 10% final OOS) with no shuffling

#### Scenario: Feature importance
- **WHEN** the direction classifier is trained
- **THEN** the pipeline SHALL compute and store feature importance rankings via LightGBM's built-in importance

### Requirement: Walk-forward validation
The direction classifier SHALL use expanding-window walk-forward validation instead of single-split validation.

#### Scenario: Expanding window
- **WHEN** walk-forward validation runs
- **THEN** each fold SHALL train on [0, t] and predict [t, t+k], advancing t by k each step

#### Scenario: No look-ahead
- **WHEN** predictions are made in walk-forward
- **THEN** only data strictly before the prediction window SHALL be used for training

#### Scenario: Aggregated metrics
- **WHEN** walk-forward validation completes
- **THEN** metrics SHALL be averaged across all folds, with per-fold metrics also available

### Requirement: Sub-model independence
Each sub-model (direction, regime, volatility) SHALL be independently trainable and replaceable without affecting others.

#### Scenario: Independent training
- **WHEN** the direction classifier is retrained
- **THEN** the regime classifier and volatility forecaster SHALL remain unchanged

#### Scenario: Model swapping
- **WHEN** a sub-model is replaced with a new implementation
- **THEN** the combiner SHALL continue to function as long as the replacement produces the same output type
