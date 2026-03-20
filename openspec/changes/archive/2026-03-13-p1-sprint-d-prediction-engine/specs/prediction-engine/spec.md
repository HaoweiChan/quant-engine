## ADDED Requirements

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
