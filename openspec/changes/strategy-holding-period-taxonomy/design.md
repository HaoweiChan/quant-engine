## Context

The strategy directory currently uses a two-level hierarchy: `intraday/` vs `daily/` as the primary axis, with entry logic (`breakout/`, `mean_reversion/`, `trend_following/`) as the secondary axis. The `StrategyTimeframe` enum has three values (`INTRADAY`, `DAILY`, `MULTI_DAY`) that conflate signal bar size with position holding duration.

This structure worked when there were 2-3 strategies, but with 9 strategies spanning 20-minute scalps to multi-week pyramids, the binary split provides no useful information. The backtester, optimizer, and dashboard all need to know holding period and stop architecture independently — information the current metadata doesn't carry.

**Affected modules**: `src/strategies/` (all files), `src/strategies/registry.py`, `src/strategies/scaffold.py`, `src/api/routes/backtest.py`, `src/mcp_server/tools.py`, `frontend/src/stores/strategyStore.ts`

## Goals / Non-Goals

**Goals:**
- Reorganize strategy directories by holding period (short_term / medium_term / swing) with entry logic as secondary axis
- Replace `StrategyTimeframe` with `SignalTimeframe`, `HoldingPeriod`, and `StopArchitecture` enums
- Expand `STRATEGY_META` to carry signal timeframe, holding period, expected duration, tradeable sessions, and stop architecture
- Retain flat-name aliases in registry (e.g., `"pyramid"` → `"swing/trend_following/pyramid_wrapper"`)
- Add registry query methods for multi-dimensional filtering

**Non-Goals:**
- Changing PositionEngine, EntryPolicy, AddPolicy, or StopPolicy interfaces
- Modifying backtester simulation logic or Monte Carlo engine
- Adding new strategies (this is purely organizational)
- Migrating param_registry SQLite data (pre-production; no migration needed)
- Changing TOML config file format or location

## Decisions

### Decision 1: Holding period as primary directory axis

**Choice**: `short_term/` (<4h), `medium_term/` (4h-5d), `swing/` (1-4wk)

**Why not keep timeframe as primary axis with finer granularity?**
Signal timeframe (1min vs 15min vs daily) determines indicator calculation, but holding period determines risk profile, quality gates, and operational behavior (session-close flattening). Two strategies can use 15min bars but have completely different risk profiles if one holds 30 minutes and the other holds 3 days.

**Why not flat structure with all metadata in STRATEGY_META?**
Directory structure provides immediate visual organization and constrains where new strategies go. A flat folder with 20+ files and metadata-only classification requires reading each file to understand the landscape.

**Strategy placement:**

| Strategy | Current | New | Rationale |
|----------|---------|-----|-----------|
| ta_orb | intraday/breakout/ | short_term/breakout/ | 30min-2h holds, session-scoped |
| structural_orb | intraday/breakout/ | short_term/breakout/ | Similar ORB pattern, session-scoped |
| keltner_vwap_breakout | intraday/breakout/ | short_term/breakout/ | Intraday breakout, session-scoped |
| atr_mean_reversion | intraday/mean_reversion/ | short_term/mean_reversion/ | 20-60min holds |
| bollinger_pinbar | intraday/mean_reversion/ | short_term/mean_reversion/ | Intraday mean reversion snap-back |
| vwap_statistical_deviation | intraday/mean_reversion/ | short_term/mean_reversion/ | Intraday VWAP reversion |
| ema_trend_pullback | intraday/trend_following/ | medium_term/trend_following/ | 3-12h holds, may span sessions |
| donchian_trend_strength | intraday/trend_following/ | medium_term/trend_following/ | Multi-hour trend, may span sessions |
| pyramid_wrapper | daily/trend_following/ | swing/trend_following/ | 1-4 week holds |

### Decision 2: Three new enums replace StrategyTimeframe

```
src/strategies/__init__.py

class SignalTimeframe(str, Enum):
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    ONE_HOUR = "1hour"
    DAILY = "daily"

class HoldingPeriod(str, Enum):
    SHORT_TERM = "short_term"      # < 4 hours
    MEDIUM_TERM = "medium_term"    # 4 hours - 5 days
    SWING = "swing"                # 1-4 weeks

class StopArchitecture(str, Enum):
    INTRADAY = "intraday"    # Must flatten before session end
    SWING = "swing"          # Can hold multiple days
```

**Why not keep StrategyTimeframe alongside?** It would create confusion about which field to check. Clean break with aliases is simpler. The old enum will be removed; any code referencing `StrategyTimeframe` will get an import error (easy to find and fix).

**Why only INTRADAY and SWING for StopArchitecture (no DAILY)?** Currently all strategies are either session-flat or multi-day. A DAILY architecture (hold overnight but same-day setup) doesn't exist yet. Add it when the first strategy needs it — YAGNI.

### Decision 3: Expanded STRATEGY_META schema

```python
STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,              # unchanged
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,     # NEW: bar used for signals
    "holding_period": HoldingPeriod.SHORT_TERM,          # NEW: expected duration
    "stop_architecture": StopArchitecture.INTRADAY,      # NEW: session-close behavior
    "expected_duration_minutes": (30, 120),              # NEW: (min, max) tuple
    "tradeable_sessions": ["day", "night"],              # REPLACES: "session" field
    "description": "...",                                # unchanged
    # optional fields carried forward:
    "bars_per_day": 1050,
    "presets": {...},
    "paper": "...",
}
```

The old `"timeframe"` key is removed. The old `"session"` key is renamed to `"tradeable_sessions"` and normalized to always be a list.

### Decision 4: Flat-name slug aliases in registry

The alias map covers short convenience names only (no old `intraday/`/`daily/` path aliases — system is pre-production):

```python
_SLUG_ALIASES: dict[str, str] = {
    # flat name aliases
    "ta_orb": "short_term/breakout/ta_orb",
    "structural_orb": "short_term/breakout/structural_orb",
    "keltner_vwap_breakout": "short_term/breakout/keltner_vwap_breakout",
    "atr_mean_reversion": "short_term/mean_reversion/atr_mean_reversion",
    "bollinger_pinbar": "short_term/mean_reversion/bollinger_pinbar",
    "vwap_statistical_deviation": "short_term/mean_reversion/vwap_statistical_deviation",
    "ema_trend_pullback": "medium_term/trend_following/ema_trend_pullback",
    "donchian_trend_strength": "medium_term/trend_following/donchian_trend_strength",
    "pyramid": "swing/trend_following/pyramid_wrapper",
    "pyramid_wrapper": "swing/trend_following/pyramid_wrapper",
}
```

### Decision 5: New registry query methods

```python
def get_by_holding_period(period: HoldingPeriod) -> dict[str, StrategyInfo]: ...
def get_by_signal_timeframe(tf: SignalTimeframe) -> dict[str, StrategyInfo]: ...
def get_by_session(session: str) -> dict[str, StrategyInfo]: ...
```

The existing `get_by_timeframe()` is removed (the enum it filters on no longer exists). `get_by_category()` remains unchanged.

### Decision 6: StrategyInfo dataclass update

```python
@dataclass
class StrategyInfo:
    name: str
    slug: str
    module: str
    factory: str
    param_schema: dict[str, dict]
    meta: dict
    category: StrategyCategory | None = None
    holding_period: HoldingPeriod | None = None        # replaces timeframe
    signal_timeframe: SignalTimeframe | None = None     # new
    stop_architecture: StopArchitecture | None = None   # new
```

## Risks / Trade-offs

**[Risk] Old slug references in code or configs**
Mitigation: System is pre-production — all `intraday/` and `daily/` slug references have been deleted from the codebase. No external systems to migrate.

**[Risk] File moves may break git blame history**
Mitigation: Use `git mv` for all file moves so git tracks renames. This preserves `git log --follow` history.

**[Risk] medium_term strategies (ema_trend_pullback, donchian_trend_strength) are currently forced flat at session close by the intraday rule**
Mitigation: These strategies stay `StopArchitecture.INTRADAY` for now — the directory move is about classification, not changing their runtime behavior. If we later want them to hold overnight, that's a separate change requiring new risk analysis.

**[Risk] Frontend groups strategies by old categories**
Mitigation: Update frontend strategy store to use new `holding_period` field from the API response. The API already returns `meta` dict which will carry the new fields.

**[Trade-off] Three enums instead of one adds complexity**
Accepted: The three dimensions are genuinely independent. A strategy can use 15min bars (SignalTimeframe) with short_term holding (HoldingPeriod) and intraday flattening (StopArchitecture), or 15min bars with medium_term holding and swing architecture. Collapsing these into one enum loses information.

## Migration Plan

1. Create new directory structure alongside old (both exist temporarily)
2. Move files with `git mv` one at a time
3. Update `__init__.py` with new enums (remove `StrategyTimeframe` entirely)
4. Update each strategy file's `STRATEGY_META`
5. Update registry with flat-name alias map and new query methods
6. Update scaffold template
7. Update API/MCP consumers
8. Update frontend
9. Remove old empty directories
10. Run full test suite + backtest validation

**Rollback**: `git revert` the merge commit. Alias map means no data migration is needed in either direction.
