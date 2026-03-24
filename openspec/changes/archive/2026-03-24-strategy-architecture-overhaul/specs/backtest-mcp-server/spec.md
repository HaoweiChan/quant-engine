## MODIFIED Requirements

### Requirement: read_strategy_file tool
The server SHALL expose a `read_strategy_file` tool that returns the content of a strategy policy file. The tool SHALL support path-like filenames for nested directory structures (e.g., `"intraday/breakout/ta_orb"`).

```python
@app.tool()
async def read_strategy_file(filename: str) -> dict: ...
```

#### Scenario: Read nested strategy file
- **WHEN** `read_strategy_file` is called with `filename="intraday/breakout/ta_orb"`
- **THEN** it SHALL return the full content of `src/strategies/intraday/breakout/ta_orb.py` along with the filename and last-modified timestamp

#### Scenario: Read with legacy flat filename (backward compat)
- **WHEN** `read_strategy_file` is called with `filename="ta_orb"` and a slug alias exists
- **THEN** it SHALL resolve the alias and return the content from the nested location

#### Scenario: Read non-existent file
- **WHEN** `read_strategy_file` is called with a filename that doesn't exist in `src/strategies/`
- **THEN** it SHALL return an error listing available strategy files with their path-like stems

#### Scenario: List available files
- **WHEN** `read_strategy_file` is called with `filename="__list__"`
- **THEN** it SHALL return a list of all strategy `.py` files with path-like stems, sizes, and timestamps

### Requirement: write_strategy_file tool
The server SHALL expose a `write_strategy_file` tool that validates and writes a strategy policy file. The tool SHALL support path-like filenames and auto-create parent directories.

```python
@app.tool()
async def write_strategy_file(filename: str, content: str) -> dict: ...
```

#### Scenario: Write to nested path
- **WHEN** `write_strategy_file` is called with `filename="intraday/trend_following/ema_pullback"` and valid content
- **THEN** it SHALL create `src/strategies/intraday/trend_following/` if needed, write the file, and invalidate the registry cache

#### Scenario: Valid strategy write
- **WHEN** `write_strategy_file` is called with syntactically valid Python containing a class implementing a policy ABC
- **THEN** it SHALL backup the existing file (if any), write the new content, invalidate the registry cache, and return success with a reminder to run `run_monte_carlo`

#### Scenario: Registry invalidated after write
- **WHEN** `write_strategy_file` completes successfully
- **THEN** the strategy registry cache SHALL be invalidated so `discover_strategies()` finds the new strategy immediately

#### Scenario: Syntax error rejection
- **WHEN** the `content` has a Python syntax error
- **THEN** it SHALL return `{"success": false, "errors": [...]}` without modifying any file

#### Scenario: Forbidden import rejection
- **WHEN** content contains forbidden imports
- **THEN** it SHALL return `{"success": false, "errors": [...]}` without modifying any file

## MODIFIED Requirements

### Requirement: Strategy factory resolution
The facade module SHALL resolve strategy factories exclusively through the strategy registry, eliminating the hardcoded `_BUILTIN_FACTORIES` dict.

```python
def resolve_factory(strategy: str) -> Any:
    """Return a callable engine factory.

    Resolution order:
    1. Registry lookup (slug or alias)
    2. "module:factory" format (external strategies)
    3. Raise ValueError
    """
```

#### Scenario: Resolve by new path-like slug
- **WHEN** `resolve_factory("intraday/breakout/ta_orb")` is called
- **THEN** it SHALL import `src.strategies.intraday.breakout.ta_orb` and return `create_ta_orb_engine`

#### Scenario: Resolve by legacy flat slug via alias
- **WHEN** `resolve_factory("ta_orb")` is called
- **THEN** it SHALL resolve the alias to `"intraday/breakout/ta_orb"` and return the factory

#### Scenario: Resolve by module:factory format
- **WHEN** `resolve_factory("my_module:my_factory")` is called
- **THEN** it SHALL import `my_module` and return `my_factory`

#### Scenario: Unknown strategy raises ValueError
- **WHEN** `resolve_factory("nonexistent")` is called
- **THEN** it SHALL raise `ValueError` listing all available strategy slugs from the registry

#### Scenario: Newly written strategy resolvable without restart
- **WHEN** a new strategy file is written via `write_strategy_file` and the registry is invalidated
- **THEN** `resolve_factory` with the new slug SHALL succeed without MCP server restart

## ADDED Requirements

### Requirement: scaffold_strategy MCP tool
The server SHALL expose a `scaffold_strategy` tool that generates strategy boilerplate for the agent to review before writing.

```python
Tool(
    name="scaffold_strategy",
    description=(
        "Generate a complete strategy boilerplate file with correct conventions. "
        "Returns the generated Python content — does NOT write the file. "
        "After reviewing, use write_strategy_file to save it. "
        "The scaffolded strategy will be immediately discoverable by the registry."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Strategy name in snake_case (e.g., 'vwap_rubber_band')",
            },
            "category": {
                "type": "string",
                "enum": ["breakout", "mean_reversion", "trend_following"],
                "description": "Strategy category",
            },
            "timeframe": {
                "type": "string",
                "enum": ["intraday", "daily", "multi_day"],
                "description": "Strategy timeframe",
            },
            "description": {
                "type": "string",
                "description": "One-line description of the strategy",
            },
            "policies": {
                "type": "array",
                "items": {"type": "string", "enum": ["entry", "add", "stop"]},
                "description": "Which policies to scaffold (default: ['entry', 'stop'])",
            },
            "params": {
                "type": "object",
                "description": "Initial parameter definitions: {name: {type, default, min, max}}",
            },
        },
        "required": ["name", "category", "timeframe"],
    },
)
```

#### Scenario: Scaffold tool returns content without writing
- **WHEN** the agent calls `scaffold_strategy` with `name="ema_pullback"`
- **THEN** it SHALL return the generated content, slug, and path but SHALL NOT write any file to disk

#### Scenario: Scaffold result guides next steps
- **WHEN** `scaffold_strategy` returns a result
- **THEN** the `next_steps` field SHALL be `["write_strategy_file", "run_monte_carlo"]`

#### Scenario: Tool description guides workflow
- **WHEN** the agent reads the `scaffold_strategy` tool description
- **THEN** it SHALL indicate that `write_strategy_file` is needed to persist the result
