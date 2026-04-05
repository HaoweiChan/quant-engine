## 1. Enum and Type Definitions

- [x] 1.1 Add `SignalTimeframe`, `HoldingPeriod`, `StopArchitecture` enums to `src/strategies/__init__.py`. Remove `StrategyTimeframe` enum. Add `get_quality_thresholds()` function. Update `__all__` exports. **Accept**: `from src.strategies import SignalTimeframe, HoldingPeriod, StopArchitecture` succeeds; `StrategyTimeframe` import raises `ImportError`.
- [x] 1.2 Update `StrategyInfo` dataclass in `src/strategies/registry.py`: replace `timeframe` field with `holding_period`, `signal_timeframe`, `stop_architecture` fields. **Accept**: `StrategyInfo` has the three new `Optional` fields; no `timeframe` field.

## 2. Directory Structure

- [x] 2.1 Create new directory tree: `short_term/{breakout,mean_reversion,trend_following}/`, `medium_term/{breakout,mean_reversion,trend_following}/`, `swing/{breakout,mean_reversion,trend_following}/` under `src/strategies/`. Add `__init__.py` to each new directory. **Accept**: all 9 directories exist with `__init__.py`.
- [x] 2.2 Move strategy files with `git mv`: `intraday/breakout/{ta_orb,structural_orb,keltner_vwap_breakout}.py` → `short_term/breakout/`, `intraday/mean_reversion/{atr_mean_reversion,bollinger_pinbar,vwap_statistical_deviation}.py` → `short_term/mean_reversion/`, `intraday/trend_following/{ema_trend_pullback,donchian_trend_strength}.py` → `medium_term/trend_following/`, `daily/trend_following/pyramid_wrapper.py` → `swing/trend_following/`. **Accept**: `git status` shows renames; old paths gone.
- [x] 2.3 Remove empty old directories (`intraday/`, `daily/`) and their `__init__.py` files. **Accept**: `src/strategies/intraday/` and `src/strategies/daily/` no longer exist.

## 3. Strategy META Updates

- [x] 3.1 Update `STRATEGY_META` in `short_term/breakout/ta_orb.py`: replace `timeframe` with `signal_timeframe=SignalTimeframe.FIFTEEN_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, add `expected_duration_minutes=(30, 120)`, rename `session` to `tradeable_sessions=["day"]`. Update imports. **Accept**: module imports cleanly; META has all 7 required keys; no `timeframe` key.
- [x] 3.2 Update `STRATEGY_META` in `short_term/breakout/structural_orb.py`: `signal_timeframe=SignalTimeframe.FIFTEEN_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(30, 120)`, `tradeable_sessions=["day"]`. **Accept**: same as 3.1.
- [x] 3.3 Update `STRATEGY_META` in `short_term/breakout/keltner_vwap_breakout.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(20, 120)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.4 Update `STRATEGY_META` in `short_term/mean_reversion/atr_mean_reversion.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(20, 60)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.5 Update `STRATEGY_META` in `short_term/mean_reversion/bollinger_pinbar.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(20, 60)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.6 Update `STRATEGY_META` in `short_term/mean_reversion/vwap_statistical_deviation.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.SHORT_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(20, 60)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.7 Update `STRATEGY_META` in `medium_term/trend_following/ema_trend_pullback.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.MEDIUM_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(180, 720)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.8 Update `STRATEGY_META` in `medium_term/trend_following/donchian_trend_strength.py`: `signal_timeframe=SignalTimeframe.ONE_MIN`, `holding_period=HoldingPeriod.MEDIUM_TERM`, `stop_architecture=StopArchitecture.INTRADAY`, `expected_duration_minutes=(180, 720)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.
- [x] 3.9 Update `STRATEGY_META` in `swing/trend_following/pyramid_wrapper.py`: `signal_timeframe=SignalTimeframe.DAILY`, `holding_period=HoldingPeriod.SWING`, `stop_architecture=StopArchitecture.SWING`, `expected_duration_minutes=(10080, 40320)`, `tradeable_sessions=["day", "night"]`. **Accept**: same as 3.1.

## 4. Registry Updates

- [x] 4.1 Update `_SLUG_ALIASES` in `registry.py` with flat-name aliases only (no `intraday/`/`daily/` path aliases — system is pre-production). **Accept**: `get_info("ta_orb")` and `get_info("short_term/breakout/ta_orb")` both return the same `StrategyInfo`.
- [x] 4.2 Update `_discover()` to populate `StrategyInfo.holding_period`, `.signal_timeframe`, `.stop_architecture` from `STRATEGY_META`. Remove `timeframe` population. **Accept**: `get_all()` returns `StrategyInfo` objects with correct new fields.
- [x] 4.3 Add `get_by_holding_period()`, `get_by_signal_timeframe()`, `get_by_session()` methods. Remove `get_by_timeframe()`. **Accept**: `get_by_holding_period(HoldingPeriod.SHORT_TERM)` returns 6 strategies; `get_by_session("day")` returns all 9.

## 5. Scaffold Update

- [x] 5.1 Update `scaffold.py` function signature: replace `timeframe` param with `holding_period`, `signal_timeframe`, `stop_architecture`, `tradeable_sessions`, `expected_duration_minutes`. Update template generation to use new directory paths and expanded META. **Accept**: `scaffold_strategy(name="test", category=StrategyCategory.BREAKOUT, holding_period=HoldingPeriod.SHORT_TERM, signal_timeframe=SignalTimeframe.FIFTEEN_MIN)` returns slug `"short_term/breakout/test"` and content with all new META fields.

## 6. Consumer Updates

- [x] 6.1 Update `src/api/routes/backtest.py`: replace any `StrategyTimeframe` references with new enums. Ensure API responses include `holding_period`, `signal_timeframe`, `stop_architecture` in strategy metadata. **Accept**: `/api/strategies` endpoint returns new classification fields.
- [x] 6.2 Update `src/mcp_server/tools.py` and `src/mcp_server/facade.py`: replace `StrategyTimeframe` references. Ensure `get_parameter_schema` tool returns new META fields. **Accept**: MCP `get_parameter_schema` response includes new fields.
- [x] 6.3 Update `src/simulator/backtester.py`: replace any `StrategyTimeframe` references with new enums if present. **Accept**: backtester imports resolve cleanly.
- [x] 6.4 Update `src/strategies/param_loader.py`: ensure slug resolution uses the registry alias map for config file lookups. **Accept**: `load_strategy_params("ta_orb")` resolves to canonical new slug via flat-name alias.
- [x] 6.5 Update `frontend/src/stores/strategyStore.ts`: update type definitions for new META fields. Update any grouping logic to use `holding_period` instead of `timeframe`. **Accept**: frontend TypeScript compiles without errors.

## 7. Validation and Testing

- [x] 7.1 Run `python -c "from src.strategies.registry import get_all; print(list(get_all().keys()))"` — verify all 9 strategies discovered with new slugs. **Accept**: output shows 9 strategies with `short_term/`, `medium_term/`, `swing/` prefixes.
- [x] 7.2 Run `python -c "from src.strategies.registry import validate_schemas; print(validate_schemas())"` — verify schema-factory consistency. **Accept**: empty list (no mismatches).
- [x] 7.3 Run existing test suite (`pytest tests/`) — verify no regressions from file moves and enum changes. **Accept**: all tests pass.
- [x] 7.4 Run a single backtest via MCP tool for one strategy from each holding period (e.g., `atr_mean_reversion`, `ema_trend_pullback`, `pyramid_wrapper`) to verify end-to-end path works. **Accept**: backtests complete without import or slug resolution errors.
