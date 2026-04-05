"""Strategy scaffold generator — MCP tool + CLI.

Generates convention-compliant strategy boilerplate that is immediately
discoverable by the strategy registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory

_STRATEGIES_DIR = Path(__file__).resolve().parent

_DEFAULT_PARAMS: dict[str, dict] = {
    "lookback": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Lookback period (bars).",
    },
}


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
    """Generate a complete strategy file.

    Returns:
        slug: path-like slug for registry
        path: full file path
        content: complete Python source
        next_steps: suggested MCP tool calls
    """
    pol = policies or ["entry", "stop"]
    par = params or _DEFAULT_PARAMS
    sessions = tradeable_sessions or ["day", "night"]
    # Default stop_architecture based on holding period
    if stop_architecture is None:
        stop_architecture = (
            StopArchitecture.SWING if holding_period == HoldingPeriod.SWING
            else StopArchitecture.INTRADAY
        )
    # Default expected duration based on holding period
    if expected_duration_minutes is None:
        _defaults = {
            HoldingPeriod.SHORT_TERM: (20, 240),
            HoldingPeriod.MEDIUM_TERM: (240, 7200),
            HoldingPeriod.SWING: (10080, 40320),
        }
        expected_duration_minutes = _defaults[holding_period]
    subdir = f"{holding_period.value}/{category.value}"
    slug = f"{subdir}/{name}"
    filepath = _STRATEGIES_DIR / subdir / f"{name}.py"
    if filepath.exists():
        return {
            "error": f"Strategy file already exists at {filepath}",
            "hint": "Use read_strategy_file to view, or choose a different name",
        }
    class_prefix = "".join(w.capitalize() for w in name.split("_"))
    content = _generate_content(
        name=name,
        class_prefix=class_prefix,
        category=category,
        holding_period=holding_period,
        signal_timeframe=signal_timeframe,
        stop_architecture=stop_architecture,
        description=description,
        policies=pol,
        params=par,
        tradeable_sessions=sessions,
        expected_duration_minutes=expected_duration_minutes,
    )
    return {
        "slug": slug,
        "path": str(filepath),
        "content": content,
        "next_steps": ["write_strategy_file", "run_monte_carlo"],
    }


def _generate_content(
    *,
    name: str,
    class_prefix: str,
    category: StrategyCategory,
    holding_period: HoldingPeriod,
    signal_timeframe: SignalTimeframe,
    stop_architecture: StopArchitecture,
    description: str,
    policies: list[str],
    params: dict[str, dict],
    tradeable_sessions: list[str],
    expected_duration_minutes: tuple[int, int],
) -> str:
    lines: list[str] = []
    desc = description or f"{class_prefix} strategy."
    lines.append(f'"""{desc}"""')
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from collections import deque")
    lines.append("from typing import TYPE_CHECKING")
    lines.append("")
    # Policy imports
    policy_imports = ["EntryPolicy"]
    if "add" in policies:
        policy_imports.append("AddPolicy")
    else:
        policy_imports.append("NoAddPolicy")
    policy_imports.append("StopPolicy")
    lines.append(f"from src.core.policies import {', '.join(sorted(policy_imports))}")
    type_imports = [
        "AccountState",
        "EngineConfig",
        "EngineState",
        "EntryDecision",
        "MarketSignal",
        "MarketSnapshot",
    ]
    if "stop" in policies:
        type_imports.append("Position")
    lines.append(f"from src.core.types import ({', '.join(sorted(type_imports))})")
    lines.append("from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory")
    if holding_period in (HoldingPeriod.SHORT_TERM, HoldingPeriod.MEDIUM_TERM):
        lines.append("from src.strategies._session_utils import in_day_session, in_force_close, in_night_session")
    lines.append("")
    lines.append("if TYPE_CHECKING:")
    lines.append("    from src.core.position_engine import PositionEngine")
    lines.append("")
    lines.append("")
    # PARAM_SCHEMA
    lines.append("PARAM_SCHEMA: dict[str, dict] = {")
    for pname, pspec in params.items():
        ptype = pspec.get("type", "float")
        default = pspec.get("default", 0)
        pmin = pspec.get("min", 0)
        pmax = pspec.get("max", 100)
        pdesc = pspec.get("description", f"{pname} parameter.")
        default_repr = repr(default)
        lines.append(f'    "{pname}": {{"type": "{ptype}", "default": {default_repr}, '
                     f'"min": {pmin}, "max": {pmax},')
        lines.append(f'                 "description": "{pdesc}"}},')
    lines.append("}")
    lines.append("")
    # STRATEGY_META
    sessions_repr = repr(tradeable_sessions)
    dur_repr = repr(expected_duration_minutes)
    lines.append("STRATEGY_META: dict = {")
    lines.append(f'    "category": StrategyCategory.{category.name},')
    lines.append(f'    "signal_timeframe": SignalTimeframe.{signal_timeframe.name},')
    lines.append(f'    "holding_period": HoldingPeriod.{holding_period.name},')
    lines.append(f'    "stop_architecture": StopArchitecture.{stop_architecture.name},')
    lines.append(f'    "expected_duration_minutes": {dur_repr},')
    lines.append(f'    "tradeable_sessions": {sessions_repr},')
    lines.append(f'    "description": "{desc}",')
    lines.append("}")
    lines.append("")
    lines.append("")
    # Entry policy
    if "entry" in policies:
        lines.append(f"class {class_prefix}Entry(EntryPolicy):")
        lines.append(f'    """Entry policy for {name}."""')
        lines.append("")
        lines.append("    def __init__(")
        lines.append("        self,")
        lines.append("        lots: float = 1.0,")
        lines.append('        contract_type: str = "large",')
        for pname, pspec in params.items():
            ptype_py = "int" if pspec.get("type") == "int" else "float"
            lines.append(f"        {pname}: {ptype_py} = {repr(pspec.get('default', 0))},")
        lines.append("    ) -> None:")
        lines.append("        self._lots = lots")
        lines.append("        self._contract_type = contract_type")
        for pname in params:
            lines.append(f"        self._{pname} = {pname}")
        lines.append("")
        lines.append("    def should_enter(")
        lines.append("        self,")
        lines.append("        snapshot: MarketSnapshot,")
        lines.append("        signal: MarketSignal | None,")
        lines.append("        engine_state: EngineState,")
        lines.append("        account: AccountState | None = None,")
        lines.append("    ) -> EntryDecision | None:")
        lines.append('        if engine_state.mode == "halted":')
        lines.append("            return None")
        lines.append("        # TODO: implement entry logic")
        lines.append("        return None")
        lines.append("")
        lines.append("")
    # Stop policy
    if "stop" in policies:
        lines.append(f"class {class_prefix}Stop(StopPolicy):")
        lines.append(f'    """Stop policy for {name}."""')
        lines.append("")
        lines.append("    def initial_stop(")
        lines.append("        self, entry_price: float, direction: str, snapshot: MarketSnapshot,")
        lines.append("    ) -> float:")
        lines.append("        atr = snapshot.atr['daily']")
        lines.append('        if direction == "short":')
        lines.append("            return entry_price + 2.0 * atr")
        lines.append("        return entry_price - 2.0 * atr")
        lines.append("")
        lines.append("    def update_stop(")
        lines.append("        self,")
        lines.append("        position: Position,")
        lines.append("        snapshot: MarketSnapshot,")
        lines.append("        high_history: deque[float],")
        lines.append("    ) -> float:")
        lines.append("        # TODO: implement trailing stop logic")
        lines.append("        return position.stop_level")
        lines.append("")
        lines.append("")
    # Factory function
    stem = name
    lines.append(f"def create_{stem}_engine(")
    lines.append("    max_loss: float = 150_000,")
    lines.append("    lots: float = 1.0,")
    lines.append('    contract_type: str = "large",')
    for pname, pspec in params.items():
        ptype_py = "int" if pspec.get("type") == "int" else "float"
        lines.append(f"    {pname}: {ptype_py} = {repr(pspec.get('default', 0))},")
    lines.append(') -> "PositionEngine":')
    lines.append(f'    """Build a PositionEngine wired with the {name} strategy."""')
    lines.append("    from src.core.position_engine import PositionEngine")
    lines.append("")
    if "entry" in policies:
        entry_args = ["lots=lots", "contract_type=contract_type"]
        for pname in params:
            entry_args.append(f"{pname}={pname}")
        lines.append(f"    entry = {class_prefix}Entry({', '.join(entry_args)})")
    else:
        lines.append(f"    entry = {class_prefix}Entry()")
    if "add" in policies:
        lines.append(f"    add = {class_prefix}Add()")
    else:
        lines.append("    add = NoAddPolicy()")
    if "stop" in policies:
        lines.append(f"    stop = {class_prefix}Stop()")
    else:
        lines.append(f"    stop = {class_prefix}Stop()")
    lines.append("    return PositionEngine(")
    lines.append("        entry_policy=entry,")
    lines.append("        add_policy=add,")
    lines.append("        stop_policy=stop,")
    lines.append("        config=EngineConfig(max_loss=max_loss),")
    lines.append("    )")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Generate a strategy scaffold file.",
        prog="python -m src.strategies.scaffold",
    )
    parser.add_argument("name", help="Strategy name in snake_case")
    parser.add_argument("--category", required=True, choices=[c.value for c in StrategyCategory])
    parser.add_argument("--holding-period", required=True, choices=[h.value for h in HoldingPeriod])
    parser.add_argument("--signal-timeframe", required=True, choices=[t.value for t in SignalTimeframe])
    parser.add_argument("--description", default="", help="One-line description")
    parser.add_argument("--write", action="store_true", help="Write the file (default: print to stdout)")
    args = parser.parse_args()

    result = scaffold_strategy(
        name=args.name,
        category=StrategyCategory(args.category),
        holding_period=HoldingPeriod(args.holding_period),
        signal_timeframe=SignalTimeframe(args.signal_timeframe),
        description=args.description,
    )
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    if args.write:
        path = Path(result["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result["content"])
        print(f"Written: {result['path']}")
    else:
        print(result["content"])
