# mc-trade-resampling

## Purpose
TBD — synced from change `monte-carlo-enhancements`.

## Requirements

### Requirement: Trade-level P&L bootstrap
The system SHALL resample individual trade P&Ls with replacement to construct synthetic equity curves that reveal sequence dependency risk.

#### Scenario: Basic trade resampling
- **WHEN** `run_trade_resampling(trade_pnls, n_paths=1000, initial_capital=2_000_000)` is called with a list of trade P&Ls
- **THEN** it SHALL return `n_paths` equity curves, each constructed by randomly sampling `len(trade_pnls)` trades with replacement and accumulating PnL from `initial_capital`

#### Scenario: Empty trade list
- **WHEN** `trade_pnls` is an empty list
- **THEN** the function SHALL raise `ValueError` with message indicating no trades to resample

#### Scenario: Single trade
- **WHEN** `trade_pnls` contains exactly one trade
- **THEN** all paths SHALL be identical (only one trade to sample)

#### Scenario: Preserves trade magnitudes
- **WHEN** resampling is performed
- **THEN** each path SHALL use exact P&L values from the original trade list (no scaling or modification)

### Requirement: Block bootstrap option
The system SHALL support block bootstrap that preserves local structure of consecutive trades.

#### Scenario: Block bootstrap with configurable block size
- **WHEN** `run_trade_resampling(trade_pnls, n_paths=1000, block_size=5)` is called
- **THEN** it SHALL sample contiguous blocks of 5 trades (with replacement) and concatenate them to form each path

#### Scenario: Default is simple bootstrap
- **WHEN** `block_size` is not specified or is 1
- **THEN** it SHALL use standard single-trade sampling with replacement
