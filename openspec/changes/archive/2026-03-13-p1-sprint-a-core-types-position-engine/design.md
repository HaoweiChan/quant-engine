## Context

The quant engine has complete specifications (ARCHITECTURE.md, SPECS.md) and openspec specs for `core-types` and `position-engine`, but no runnable code. This sprint implements the foundational layer that all downstream modules depend on.

The existing specs define all dataclasses, interfaces, and behavioral contracts. This design addresses the structural decisions for turning those specs into a working codebase.

## Goals / Non-Goals

**Goals:**
- Implement all core types with full validation as specified in `openspec/specs/core-types/spec.md`
- Implement `PositionEngine` with all behaviors from `openspec/specs/position-engine/spec.md`
- Establish the package structure, tooling, and test patterns for the rest of the project
- Ensure all types are market-agnostic — no hardcoded prices, margins, or contract values

**Non-Goals:**
- No broker connectivity or real data (Sprint B)
- No backtesting or simulation (Sprint C)
- No prediction models (Sprint D)
- No execution engine beyond the `Order` type definition
- No persistence layer — all state is in-memory

## Decisions

### Package layout

```
quant_engine/
├── core/
│   ├── __init__.py
│   ├── types.py          # All dataclasses + RiskAction enum
│   ├── adapter.py         # BaseAdapter ABC
│   └── position_engine.py # PositionEngine class
└── __init__.py

tests/
├── conftest.py            # Shared fixtures (synthetic snapshots, signals, configs)
├── test_types.py          # Validation tests for all dataclasses
└── test_position_engine.py # Behavioral tests for PositionEngine
```

**Rationale:** Flat `core/` module keeps all foundational code together. Downstream modules (`data/`, `prediction/`, `simulator/`, `execution/`) will be sibling packages. Keeping types in a single file avoids circular imports since all dataclasses reference each other.

### Validation strategy: `__post_init__` on dataclasses

All dataclass validation (range checks, required fields, consistency) goes in `__post_init__`. This ensures invalid objects can never exist.

**Rationale:** Pydantic was considered but adds a dependency for what are simple range checks. `__post_init__` is zero-dependency and mypy-friendly. If validation grows complex later, migrating to `attrs` or pydantic is straightforward.

### PositionEngine state management: internal mutable state

`PositionEngine` holds mutable state (positions, pyramid level, highest high for trailing stop) as instance attributes. `get_state()` returns a frozen `EngineState` snapshot.

**Rationale:** The engine processes snapshots one at a time in order. No concurrency within a single engine instance. The Simulator and Backtester create separate engine instances, so shared state is not a concern.

### Configuration: PyramidConfig as constructor parameter

`PositionEngine.__init__(config: PyramidConfig)` takes a fully constructed config. No file loading, no defaults from environment. The caller (backtester, live runner, etc.) is responsible for constructing the config.

**Rationale:** Keeps the engine pure and testable. Config loading from TOML is a Sprint E concern.

### Testing: synthetic price sequences via fixtures

Tests use hand-crafted `MarketSnapshot` sequences that exercise specific behaviors (e.g., price rises to trigger pyramid add, price drops to trigger stop). No randomness in unit tests.

**Rationale:** Deterministic tests catch regressions. Monte Carlo / random testing is Sprint C's domain.

## Risks / Trade-offs

- **[Risk] Type definitions may need revision as downstream modules are built** → Mitigation: Types are dataclasses with no business logic, so adding fields is backward-compatible. Removing fields would be a breaking change tracked via openspec delta specs.
- **[Risk] `on_snapshot()` processing order is complex (6 priority steps)** → Mitigation: Each step is a private method with its own unit test. Integration tests verify the combined order.
- **[Risk] Floating-point precision in stop-level comparisons** → Mitigation: Use `math.isclose()` or tick-size-aware comparisons from `ContractSpecs.min_tick`. Document the precision contract.
