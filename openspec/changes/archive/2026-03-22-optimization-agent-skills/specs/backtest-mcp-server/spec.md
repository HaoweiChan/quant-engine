## MODIFIED Requirements

### Requirement: Tool descriptions encode optimization protocol
Each MCP tool description SHALL include guidance on when to use the tool, preconditions, and what to do after.

#### Scenario: run_monte_carlo description references skills
- **WHEN** the agent reads the `run_monte_carlo` tool description
- **THEN** it SHALL find a reference to the `quant-overfitting` skill for evaluation criteria and the `optimize-strategy` skill for the optimization protocol

#### Scenario: run_parameter_sweep description references skills
- **WHEN** the agent reads the `run_parameter_sweep` tool description
- **THEN** it SHALL find a reference to the `quant-overfitting` skill for parameter sensitivity and the `quant-pyramid-math` skill for safe parameter ranges

#### Scenario: write_strategy_file description references skills
- **WHEN** the agent reads the `write_strategy_file` tool description
- **THEN** it SHALL find a reference to the `quant-trend-following` skill for strategy design principles and the `quant-stop-diagnosis` skill for stop-loss design

#### Scenario: get_parameter_schema description references master skill
- **WHEN** the agent reads the `get_parameter_schema` tool description
- **THEN** it SHALL reference the `optimize-strategy` skill as the optimization protocol to follow
