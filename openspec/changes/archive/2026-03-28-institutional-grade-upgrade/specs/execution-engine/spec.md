## MODIFIED Requirements

### Requirement: Execution Engine interface
Execution Engine SHALL expose async `execute()` and `get_fill_stats()` methods. Now receives orders from OMS (sliced or passthrough).

```python
class ExecutionEngine(ABC):
    async def execute(self, orders: list[Order]) -> list[ExecutionResult]: ...
    def get_fill_stats(self) -> dict[str, float]: ...
```

#### Scenario: Execute orders from OMS
- **WHEN** `execute()` is awaited with a list of `Order` objects (from OMS child orders or passthrough)
- **THEN** it SHALL return a list of `ExecutionResult` objects, one per order, indicating fill status, fill price, and slippage

#### Scenario: Empty order list
- **WHEN** `execute()` is awaited with an empty list
- **THEN** it SHALL return an empty list without making any broker API calls

#### Scenario: Paper executor compatibility
- **WHEN** the paper executor's `execute()` is awaited
- **THEN** it SHALL return results immediately with no behavioral change from the synchronous version

### Requirement: Live fill comparison
Execution Engine SHALL track live fills and compare against backtest expectations for ongoing strategy validation. Extended with impact model comparison.

#### Scenario: Fill deviation tracking
- **WHEN** a live fill occurs
- **THEN** the executor SHALL record the fill price and slippage alongside the corresponding backtest expected fill (if available) for comparison

#### Scenario: Deviation statistics (extended)
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL include live-vs-backtest deviation metrics: mean fill deviation, P95 deviation, count of fills exceeding expected slippage by 2x, AND new fields: `predicted_impact_accuracy` (correlation between predicted and actual impact) and `oms_algorithm_performance` (fill quality per algorithm)

## ADDED Requirements

### Requirement: OMS integration
Execution Engine SHALL accept orders from the OMS and track parent-child order relationships.

#### Scenario: Child order tracking
- **WHEN** the OMS submits child orders from a sliced parent order
- **THEN** the Execution Engine SHALL track the parent-child relationship and aggregate fill statistics at the parent order level

#### Scenario: Parent order completion
- **WHEN** all child orders of a parent are filled
- **THEN** the Execution Engine SHALL compute the aggregate VWAP fill price and total slippage for the parent order

#### Scenario: Passthrough orders
- **WHEN** an order arrives without a parent relationship (passthrough from OMS)
- **THEN** the Execution Engine SHALL process it as a standalone order (existing behavior)

### Requirement: Impact model feedback loop
Execution Engine SHALL report actual fill impact back to the impact model for calibration.

#### Scenario: Actual impact reporting
- **WHEN** a live fill completes
- **THEN** the executor SHALL compute the actual market impact (fill_price - mid_price at order time) and publish it to the impact model

#### Scenario: Impact calibration data
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL include `impact_model_error` (mean absolute error between predicted and actual impact over recent fills)
