## ADDED Requirements

### Requirement: Configurable risk thresholds
All Risk Monitor thresholds SHALL be loaded from configuration, not hardcoded.

#### Scenario: Thresholds from config
- **WHEN** Risk Monitor is constructed
- **THEN** it SHALL load margin_ratio_threshold, signal_staleness_window, feed_staleness_window, spread_spike_multiplier, and max_loss from TOML config

#### Scenario: Override defaults
- **WHEN** a custom config provides different threshold values
- **THEN** Risk Monitor SHALL use those values instead of any hardcoded defaults

### Requirement: Phase 1 async task mode
In Phase 1, Risk Monitor SHALL run as an async task within the same process, with the ability to be extracted to a separate process in Phase 2.

#### Scenario: Async check loop
- **WHEN** Risk Monitor starts in Phase 1 mode
- **THEN** it SHALL run a periodic check loop at a configurable interval (default 30s) as an asyncio task

#### Scenario: Process extraction readiness
- **WHEN** Risk Monitor is designed
- **THEN** its interface SHALL not depend on in-process state -- all inputs come via AccountState and all outputs are RiskAction + mode changes, making future process extraction straightforward
