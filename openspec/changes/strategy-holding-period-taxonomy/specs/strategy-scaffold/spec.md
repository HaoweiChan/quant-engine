## MODIFIED Requirements

### Requirement: Strategy scaffold generation
The system SHALL provide a `src/strategies/scaffold.py` module with a `scaffold_strategy()` function that generates a complete, convention-compliant strategy file from minimal inputs.

```python
def scaffold_strategy(
    name: str,
    category: StrategyCategory,
    holding_period: HoldingPeriod,
    signal_timeframe: SignalTimeframe,
    stop_architecture: StopArchitecture | None = None,
    description: str = "",
    policies: list[str] | None = None,
    params: dict[str, dict] | None = None,
    tradeable_sessions: list[str] | None = None,
    expected_duration_minutes: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Generate a strategy file.

    If stop_architecture is None, it defaults to:
      - StopArchitecture.INTRADAY for SHORT_TERM and MEDIUM_TERM
      - StopArchitecture.SWING for SWING

    If tradeable_sessions is None, it defaults to ["day", "night"].

    Returns:
        {
            "slug": str,        # path-like slug for registry
            "path": str,        # full file path
            "content": str,     # complete Python source
            "next_steps": list, # suggested MCP tool calls
        }
    """
```

#### Scenario: Scaffold a short-term mean reversion strategy
- **WHEN** `scaffold_strategy(name="vwap_rubber_band", category=StrategyCategory.MEAN_REVERSION, holding_period=HoldingPeriod.SHORT_TERM, signal_timeframe=SignalTimeframe.FIVE_MIN)` is called
- **THEN** the returned `slug` SHALL be `"short_term/mean_reversion/vwap_rubber_band"`
- **AND** the returned `path` SHALL be `"src/strategies/short_term/mean_reversion/vwap_rubber_band.py"`
- **AND** the returned `content` SHALL contain a class `VwapRubberBandEntry` extending `EntryPolicy` with a `should_enter` method stub
- **AND** the content SHALL contain a class `VwapRubberBandStop` extending `StopPolicy` with `initial_stop` and `update_stop` method stubs
- **AND** the content SHALL contain a `create_vwap_rubber_band_engine` factory function

#### Scenario: Scaffold a swing trend following strategy
- **WHEN** `scaffold_strategy(name="weekly_breakout", category=StrategyCategory.TREND_FOLLOWING, holding_period=HoldingPeriod.SWING, signal_timeframe=SignalTimeframe.DAILY)` is called
- **THEN** the returned `slug` SHALL be `"swing/trend_following/weekly_breakout"`
- **AND** the returned `path` SHALL be `"src/strategies/swing/trend_following/weekly_breakout.py"`
- **AND** `stop_architecture` SHALL default to `StopArchitecture.SWING`

#### Scenario: Scaffold includes expanded STRATEGY_META
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.BREAKOUT, holding_period=HoldingPeriod.SHORT_TERM, signal_timeframe=SignalTimeframe.FIFTEEN_MIN, description="Test strategy")` is called
- **THEN** the returned `content` SHALL contain a `STRATEGY_META` dict with:
  - `"category": StrategyCategory.BREAKOUT`
  - `"signal_timeframe": SignalTimeframe.FIFTEEN_MIN`
  - `"holding_period": HoldingPeriod.SHORT_TERM`
  - `"stop_architecture": StopArchitecture.INTRADAY`
  - `"expected_duration_minutes"` tuple
  - `"tradeable_sessions"` list
  - `"description": "Test strategy"`

#### Scenario: Scaffold includes PARAM_SCHEMA
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.BREAKOUT, holding_period=HoldingPeriod.SHORT_TERM, signal_timeframe=SignalTimeframe.FIFTEEN_MIN, params={"lookback": {"type": "int", "default": 20, "min": 5, "max": 60}})` is called
- **THEN** the returned `content` SHALL contain a `PARAM_SCHEMA` dict with a `"lookback"` entry matching the provided spec
- **AND** the factory function's signature SHALL include `lookback: int = 20` as a keyword argument

#### Scenario: Scaffold with no custom params generates placeholder
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.TREND_FOLLOWING, holding_period=HoldingPeriod.SWING, signal_timeframe=SignalTimeframe.DAILY)` is called without `params`
- **THEN** the returned `content` SHALL contain a `PARAM_SCHEMA` with at least one placeholder parameter (e.g., `"lookback"`)

#### Scenario: Short-term scaffold imports session utils
- **WHEN** `scaffold_strategy(holding_period=HoldingPeriod.SHORT_TERM)` is called
- **THEN** the returned `content` SHALL import from `src.strategies._session_utils` for session boundary helpers

#### Scenario: Factory function uses NoAddPolicy when add not requested
- **WHEN** `scaffold_strategy(policies=["entry", "stop"])` is called (no "add")
- **THEN** the factory function SHALL use `NoAddPolicy()` as the add_policy argument

#### Scenario: Default stop architecture for medium-term
- **WHEN** `scaffold_strategy(holding_period=HoldingPeriod.MEDIUM_TERM, stop_architecture=None)` is called
- **THEN** `stop_architecture` SHALL default to `StopArchitecture.INTRADAY`
