## Purpose

MCP tool and CLI for generating strategy boilerplate with correct conventions, ensuring `discover_strategies()` auto-detects the new strategy immediately. Eliminates manual file setup and reduces errors when adding new strategies.

## Requirements

### Requirement: Strategy scaffold generation
The system SHALL provide a `src/strategies/scaffold.py` module with a `scaffold_strategy()` function that generates a complete, convention-compliant strategy file from minimal inputs.

```python
def scaffold_strategy(
    name: str,
    category: StrategyCategory,
    timeframe: StrategyTimeframe,
    description: str = "",
    policies: list[str] | None = None,
    params: dict[str, dict] | None = None,
    session: str = "both",
) -> dict[str, Any]:
    """Generate a strategy file.

    Returns:
        {
            "slug": str,        # path-like slug for registry
            "path": str,        # full file path
            "content": str,     # complete Python source
            "next_steps": list, # suggested MCP tool calls
        }
    """
```

#### Scenario: Scaffold a mean reversion intraday strategy
- **WHEN** `scaffold_strategy(name="vwap_rubber_band", category=StrategyCategory.MEAN_REVERSION, timeframe=StrategyTimeframe.INTRADAY)` is called
- **THEN** the returned `slug` SHALL be `"short_term/mean_reversion/vwap_rubber_band"`
- **AND** the returned `path` SHALL be `"src/strategies/short_term/mean_reversion/vwap_rubber_band.py"`
- **AND** the returned `content` SHALL contain a class `VwapRubberBandEntry` extending `EntryPolicy` with a `should_enter` method stub
- **AND** the content SHALL contain a class `VwapRubberBandStop` extending `StopPolicy` with `initial_stop` and `update_stop` method stubs
- **AND** the content SHALL contain a `create_vwap_rubber_band_engine` factory function

#### Scenario: Scaffold includes PARAM_SCHEMA
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.BREAKOUT, timeframe=StrategyTimeframe.DAILY, params={"lookback": {"type": "int", "default": 20, "min": 5, "max": 60}})` is called
- **THEN** the returned `content` SHALL contain a `PARAM_SCHEMA` dict with a `"lookback"` entry matching the provided spec
- **AND** the factory function's signature SHALL include `lookback: int = 20` as a keyword argument

#### Scenario: Scaffold includes STRATEGY_META with enums
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.BREAKOUT, timeframe=StrategyTimeframe.INTRADAY, description="Test strategy")` is called
- **THEN** the returned `content` SHALL contain a `STRATEGY_META` dict with `"category": StrategyCategory.BREAKOUT`, `"timeframe": StrategyTimeframe.INTRADAY`, and `"description": "Test strategy"`

#### Scenario: Scaffold with no custom params generates placeholder
- **WHEN** `scaffold_strategy(name="test", category=StrategyCategory.TREND_FOLLOWING, timeframe=StrategyTimeframe.DAILY)` is called without `params`
- **THEN** the returned `content` SHALL contain a `PARAM_SCHEMA` with at least one placeholder parameter (e.g., `"lookback"`)

#### Scenario: Intraday scaffold imports session utils
- **WHEN** `scaffold_strategy(timeframe=StrategyTimeframe.INTRADAY)` is called
- **THEN** the returned `content` SHALL import from `src.strategies._session_utils` for session boundary helpers

#### Scenario: Factory function uses NoAddPolicy when add not requested
- **WHEN** `scaffold_strategy(policies=["entry", "stop"])` is called (no "add")
- **THEN** the factory function SHALL use `NoAddPolicy()` as the add_policy argument

#### Scenario: Scaffold generates picklable factory
- **WHEN** `scaffold_strategy()` is called
- **THEN** the factory function SHALL be a module-level function (not a lambda or closure) so it can be pickled for parallel optimizer execution

### Requirement: Strategy scaffold MCP tool
The MCP server SHALL expose a `scaffold_strategy` tool that calls `scaffold_strategy()` and returns the generated content for the agent to review before writing.

```python
Tool(
    name="scaffold_strategy",
    inputSchema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Strategy name in snake_case"},
            "category": {"type": "string", "enum": ["breakout", "mean_reversion", "trend_following"]},
            "timeframe": {"type": "string", "enum": ["intraday", "daily", "multi_day"]},
            "description": {"type": "string"},
            "policies": {"type": "array", "items": {"type": "string"}},
            "params": {"type": "object"},
        },
        "required": ["name", "category", "timeframe"],
    },
)
```

#### Scenario: MCP tool returns scaffold content
- **WHEN** the agent calls `scaffold_strategy` via MCP with `name="ema_pullback"`, `category="trend_following"`, `timeframe="intraday"`
- **THEN** the tool SHALL return `{"slug": "medium_term/trend_following/ema_pullback", "path": "...", "content": "...", "next_steps": ["write_strategy_file", "run_monte_carlo"]}`

#### Scenario: MCP tool rejects invalid category
- **WHEN** the agent calls `scaffold_strategy` with `category="invalid"`
- **THEN** the tool SHALL return `{"error": "Invalid category 'invalid'. Must be one of: breakout, mean_reversion, trend_following"}`

#### Scenario: MCP tool rejects duplicate slug
- **WHEN** the agent calls `scaffold_strategy` with a `name` + `category` + `timeframe` combination whose target file already exists
- **THEN** the tool SHALL return `{"error": "Strategy file already exists at ...", "hint": "Use read_strategy_file to view, or choose a different name"}`

### Requirement: Strategy scaffold CLI
The scaffold SHALL be runnable as a CLI tool via `python -m src.strategies.scaffold`.

```
python -m src.strategies.scaffold <name> --category <cat> --timeframe <tf> [--description <desc>] [--write]
```

#### Scenario: CLI prints scaffold to stdout
- **WHEN** `python -m src.strategies.scaffold ema_pullback --category trend_following --timeframe intraday` is run without `--write`
- **THEN** it SHALL print the generated Python content to stdout without writing any file

#### Scenario: CLI writes file with --write flag
- **WHEN** `python -m src.strategies.scaffold ema_pullback --category trend_following --timeframe intraday --write` is run
- **THEN** it SHALL create the file at `src/strategies/medium_term/trend_following/ema_pullback.py` and print the path

#### Scenario: CLI refuses to overwrite existing file
- **WHEN** `--write` is used and the target file already exists
- **THEN** it SHALL print an error and exit with code 1 without modifying the file
