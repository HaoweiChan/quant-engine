## MODIFIED Requirements

### Requirement: Sequential optimization protocol
Prediction Engine parameters SHALL be optimized in Stage 1 of the sequential protocol on prediction-quality metrics only, and Stage-1 outputs SHALL be persisted as immutable inputs for Stage-2 position optimization.

#### Scenario: Stage 1 optimization uses prediction metrics
- **WHEN** prediction models are optimized
- **THEN** optimization SHALL target prediction metrics (accuracy, Brier, AUC)
- **AND** SHALL NOT use PnL-based objectives for Stage-1 model selection

#### Scenario: Walk-forward + Bayesian search compliance
- **WHEN** direction-model hyperparameters are tuned
- **THEN** tuning SHALL use Bayesian search with walk-forward validation on time-ordered splits

#### Scenario: Immutable Stage-1 handoff
- **WHEN** Stage 1 completes and Stage 2 starts
- **THEN** Stage-1 selected model outputs SHALL be frozen
- **AND** Stage-2 optimization SHALL consume those frozen outputs without refitting Stage-1 models

#### Scenario: Final OOS touched once after freeze
- **WHEN** Stage 1 and Stage 2 are both frozen
- **THEN** final OOS evaluation SHALL be executed exactly once for deployment decisioning
