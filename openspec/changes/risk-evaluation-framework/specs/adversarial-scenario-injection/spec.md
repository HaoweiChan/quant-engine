## ADDED Requirements

### Requirement: Stress scenario injection into MC paths
The system SHALL provide an adversarial injection module that embeds stress scenarios (from `src/simulator/stress.py`) at random positions within Monte Carlo equity paths.

```python
@dataclass
class InjectionConfig:
    scenario: StressScenario
    injection_probability: float = 0.3   # fraction of paths to inject into
    min_warmup_bars: int = 20            # earliest injection point
    seed: int | None = None

@dataclass
class AdversarialResult:
    clean_paths: np.ndarray              # paths without injection
    injected_paths: np.ndarray           # paths with stress events embedded
    injection_metadata: list[InjectionEvent]
    clean_metrics: MCSimulationResult
    injected_metrics: MCSimulationResult
    worst_case_terminal_equity: float
    median_impact_pct: float             # median % change in terminal equity from injection
```

#### Scenario: Default injection probability
- **WHEN** adversarial injection is run with default config
- **THEN** 30% of MC paths SHALL have a stress scenario injected at a random position

#### Scenario: Injection position constraints
- **WHEN** a stress scenario is injected into a path
- **THEN** the injection point SHALL be at least `min_warmup_bars` from the start and leave enough room for the full scenario duration before path end

#### Scenario: Multiple scenario types
- **WHEN** multiple `InjectionConfig` entries are provided
- **THEN** each path SHALL be eligible for at most one injection, with scenario type selected uniformly at random from the provided configs

#### Scenario: Injection preserves path prefix
- **WHEN** a stress scenario is injected at position `t`
- **THEN** the path values before `t` SHALL remain unchanged from the original MC path

### Requirement: Worst-case terminal equity reporting
The system SHALL report the worst-case terminal equity across all injected paths.

#### Scenario: Worst-case calculation
- **WHEN** adversarial injection completes
- **THEN** `worst_case_terminal_equity` SHALL be the minimum terminal equity across all injected paths

#### Scenario: Median impact calculation
- **WHEN** adversarial injection completes
- **THEN** `median_impact_pct` SHALL be the median percentage difference in terminal equity between each injected path and the corresponding clean path it was derived from

### Requirement: Comparison reporting
The system SHALL report clean vs. injected metrics side-by-side for comparison.

#### Scenario: Side-by-side metrics
- **WHEN** adversarial results are returned
- **THEN** the result SHALL include both `clean_metrics` (MC results from non-injected paths) and `injected_metrics` (MC results from injected paths) with identical metric structures (VaR, CVaR, P(Ruin), median final equity)

#### Scenario: Ruin probability under adversity
- **WHEN** adversarial injection completes
- **THEN** `injected_metrics.prob_ruin` SHALL reflect the ruin probability including the impact of embedded stress events
