## ADDED Requirements

### Requirement: Dual-path chart rendering
The `OHLCVChart` component SHALL use two separate rendering paths: a historical bulk load path and a live tick update path. These paths SHALL be independent `useEffect` hooks with distinct dependency arrays.

#### Scenario: Historical data triggers setData
- **WHEN** the `data` prop changes (new historical bars loaded)
- **THEN** the chart SHALL call `candleSeriesRef.current.setData()` and `volSeriesRef.current.setData()` with the full dataset
- **AND** overlays and signal markers SHALL be re-rendered

#### Scenario: Live tick triggers update
- **WHEN** `lastLiveTick` changes in the market data store
- **THEN** the chart SHALL call `candleSeriesRef.current.update()` with the tick's OHLCV values
- **AND** the chart SHALL call `volSeriesRef.current.update()` with the tick's volume and directional color
- **AND** `setData()` SHALL NOT be called

#### Scenario: Live tick on same timestamp updates current candle
- **WHEN** `.update()` is called with a timestamp matching the last candle
- **THEN** `lightweight-charts` SHALL mutate the existing candle in-place (O(1) operation)

#### Scenario: Live tick on new timestamp appends candle
- **WHEN** `.update()` is called with a timestamp newer than the last candle
- **THEN** `lightweight-charts` SHALL append a new candle to the chart (O(1) operation)

#### Scenario: No live tick available
- **WHEN** `lastLiveTick` is `null` (no ticks received yet or store reset)
- **THEN** the live update effect SHALL skip without calling `.update()`

### Requirement: Volume bar color reflects tick direction
The live volume update SHALL use directional coloring consistent with historical rendering.

#### Scenario: Bullish tick volume color
- **WHEN** `lastLiveTick.close >= lastLiveTick.open`
- **THEN** the volume bar color SHALL be `rgba(38,166,154,0.3)` (green)

#### Scenario: Bearish tick volume color
- **WHEN** `lastLiveTick.close < lastLiveTick.open`
- **THEN** the volume bar color SHALL be `rgba(255,82,82,0.3)` (red)
