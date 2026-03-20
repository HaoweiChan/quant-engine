## Why

The platform has no runnable code yet. Core types and the Position Engine are the foundational building blocks that every other module depends on — Data Layer produces `MarketSnapshot`, Prediction Engine produces `MarketSignal`, Execution Engine consumes `Order`, and Risk Monitor reads `EngineState`. Without these types and the engine that wires them together, no downstream work can begin.

## What Changes

- Implement all shared dataclasses: `MarketSnapshot`, `MarketSignal`, `Order`, `ContractSpecs`, `PyramidConfig`, `Position`, `EngineState`, `AccountState`, `RiskAction`
- Implement the abstract `BaseAdapter` interface that all market adapters will extend
- Implement `PositionEngine` with full pyramid entry/add logic, 3-layer stop-loss (initial → breakeven → trailing), Kelly position sizing, margin safety, circuit breaker, and mode switching
- Implement validation on all types (range checks, consistency checks, required-field enforcement)
- Build a comprehensive unit test suite using synthetic price data to verify every Position Engine behavior

## Capabilities

### New Capabilities

_(none — all capabilities already have specs)_

### Modified Capabilities

- `core-types`: Implement from existing spec — all dataclasses, enums, validation, and the `BaseAdapter` abstract class
- `position-engine`: Implement from existing spec — entry logic, pyramid logic, 3-layer stop-loss, margin safety, circuit breaker, mode switching, Kelly sizing

## Impact

- **New packages**: `quant_engine.core.types`, `quant_engine.core.position_engine`
- **Dependencies**: Python 3.12+ standard library only (dataclasses, enum, typing, datetime). No external packages needed for this sprint.
- **Testing**: pytest with synthetic `MarketSnapshot` sequences. No broker or data dependencies.
- **Downstream unblocked**: Sprint B (Data Layer), Sprint C (Backtester), Sprint D (Prediction Engine) can all begin consuming these types once this sprint completes.
