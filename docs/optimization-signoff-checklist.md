# Optimization Sign-Off Checklist

- Classify strategy type via `get_parameter_schema` before any tuning.
- Use synthetic runs (`run_backtest`, `run_monte_carlo`, research sweeps) only for exploration.
- For final sign-off, run real-data validation with `run_backtest_realdata` and/or `run_parameter_sweep(mode="production_intent")`.
- Treat sign-off as valid only when `data_source == "real"` and `termination_eligible == true`.
- Reject candidates if real-data OOS metrics miss trade-count/expectancy/objective gates.
- Record symbol/date range and source label in the final optimization summary.
