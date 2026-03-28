import { useEffect } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { useStrategyStore } from "@/stores/strategyStore";
import { useBacktestStore } from "@/stores/backtestStore";


const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  outline: "none",
};

export function StrategyParamSidebar() {
  const strategies = useStrategyStore((s) => s.strategies);
  const strategy = useStrategyStore((s) => s.strategy);
  const symbol = useStrategyStore((s) => s.symbol);
  const startDate = useStrategyStore((s) => s.startDate);
  const endDate = useStrategyStore((s) => s.endDate);
  const slippageBps = useStrategyStore((s) => s.slippageBps);
  const commissionBps = useStrategyStore((s) => s.commissionBps);
  const initialCapital = useStrategyStore((s) => s.initialCapital);
  const maxLoss = useStrategyStore((s) => s.maxLoss);
  const params = useStrategyStore((s) => s.params);
  const setStrategy = useStrategyStore((s) => s.setStrategy);
  const setSymbol = useStrategyStore((s) => s.setSymbol);
  const setDates = useStrategyStore((s) => s.setDates);
  const setCosts = useStrategyStore((s) => s.setCosts);
  const setParam = useStrategyStore((s) => s.setParam);
  const setInitialCapital = useStrategyStore((s) => s.setInitialCapital);
  const setMaxLoss = useStrategyStore((s) => s.setMaxLoss);
  const loadStrategies = useStrategyStore((s) => s.loadStrategies);
  const storeLoading = useStrategyStore((s) => s.loading);
  const locked = useStrategyStore((s) => s.locked);
  const backtestLoading = useBacktestStore((s) => s.loading);
  const disabled = storeLoading || backtestLoading || locked;
  const currentStrat = strategies.find((s) => s.slug === strategy);

  useEffect(() => {
    if (strategies.length === 0) loadStrategies();
  }, []);

  return (
    <Sidebar>
      <SectionLabel>STRATEGY</SectionLabel>
      <ParamInput label="Strategy">
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        >
          {strategies.length === 0 && <option value="">Loading…</option>}
          {strategies.map((s) => (
            <option key={s.slug} value={s.slug}>{s.name}</option>
          ))}
        </select>
      </ParamInput>
      <ParamInput label="Contract">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        >
          <option value="TX">TX</option>
          <option value="MTX">MTX</option>
        </select>
      </ParamInput>
      <ParamInput label="From">
        <input
          type="text"
          value={startDate}
          onChange={(e) => setDates(e.target.value, endDate)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="To">
        <input
          type="text"
          value={endDate}
          onChange={(e) => setDates(startDate, e.target.value)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="Timeframe">
        <select
          value={params.bar_agg ?? 1}
          onChange={(e) => setParam("bar_agg", Number(e.target.value))}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        >
          <option value={1}>1 min</option>
          <option value={3}>3 min</option>
          <option value={5}>5 min</option>
          <option value={15}>15 min</option>
          <option value={30}>30 min</option>
          <option value={60}>60 min</option>
        </select>
      </ParamInput>
      <ParamInput label="Init Capital ($)">
        <input
          type="number"
          value={initialCapital}
          step={100000}
          onChange={(e) => setInitialCapital(Number(e.target.value))}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="Max Loss ($)">
        <input
          type="number"
          value={maxLoss}
          step={10000}
          onChange={(e) => setMaxLoss(Number(e.target.value))}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
      <SectionLabel>COST MODEL</SectionLabel>
      <ParamInput label="Slippage (bps)">
        <input
          type="number"
          value={slippageBps}
          step={1}
          min={0}
          onChange={(e) => setCosts(Number(e.target.value), commissionBps)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="Commission (bps)">
        <input
          type="number"
          value={commissionBps}
          step={1}
          min={0}
          onChange={(e) => setCosts(slippageBps, Number(e.target.value))}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
      <SectionLabel>STRATEGY PARAMETERS</SectionLabel>
      {currentStrat?.param_grid &&
        Object.entries(currentStrat.param_grid)
          .filter(([key]) => key !== "bar_agg")
          .map(([key, cfg]) => (
            <ParamInput key={key} label={cfg.label || key}>
              <input
                type="number"
                value={params[key] ?? 0}
                step={cfg.type === "int" ? 1 : 0.1}
                onChange={(e) => setParam(key, Number(e.target.value))}
                disabled={disabled}
                className="w-full rounded px-1.5 py-1 text-[11px]"
                style={inputStyle}
              />
            </ParamInput>
          ))}
    </Sidebar>
  );
}
