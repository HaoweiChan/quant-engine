import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { useStrategyStore } from "@/stores/strategyStore";
import { useBacktestStore } from "@/stores/backtestStore";

/** A number input that allows free typing by buffering the raw string locally. */
function NumericInput({
  value,
  onChange,
  disabled,
  step,
  className,
  style,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  step?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => { setRaw(String(value)); }, [value]);
  return (
    <input
      type="text"
      inputMode="decimal"
      value={raw}
      onChange={(e) => {
        const s = e.target.value;
        setRaw(s);
        const n = Number(s);
        if (s !== "" && !isNaN(n)) onChange(n);
      }}
      onBlur={() => {
        const n = Number(raw);
        if (raw === "" || isNaN(n)) {
          setRaw(String(value));
        } else {
          onChange(n);
          setRaw(String(n));
        }
      }}
      disabled={disabled}
      step={step}
      className={className}
      style={style}
    />
  );
}


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
  const commissionFixed = useStrategyStore((s) => s.commissionFixed);
  const initialCapital = useStrategyStore((s) => s.initialCapital);
  const maxLoss = useStrategyStore((s) => s.maxLoss);
  const params = useStrategyStore((s) => s.params);
  const setStrategy = useStrategyStore((s) => s.setStrategy);
  const setSymbol = useStrategyStore((s) => s.setSymbol);
  const setDates = useStrategyStore((s) => s.setDates);
  const setCosts = useStrategyStore((s) => s.setCosts);
  const setCommissionFixed = useStrategyStore((s) => s.setCommissionFixed);
  const setParam = useStrategyStore((s) => s.setParam);
  const setInitialCapital = useStrategyStore((s) => s.setInitialCapital);
  const setMaxLoss = useStrategyStore((s) => s.setMaxLoss);
  const loadStrategies = useStrategyStore((s) => s.loadStrategies);
  const reloadStrategies = useStrategyStore((s) => s.reloadStrategies);
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
        <div className="flex gap-1 items-center w-full">
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            disabled={disabled}
            className="flex-1 min-w-0 rounded px-1.5 py-1 text-[11px]"
            style={inputStyle}
          >
            {strategies.length === 0 && <option value="">Loading…</option>}
            {strategies.map((s) => (
              <option key={s.slug} value={s.slug}>{s.name}</option>
            ))}
          </select>
          <button
            onClick={() => reloadStrategies()}
            disabled={disabled}
            title="Reload strategies"
            className="shrink-0 rounded px-1 py-1 text-[11px] hover:opacity-80"
            style={{
              background: "var(--color-qe-input)",
              border: "1px solid var(--color-qe-input-border)",
              color: "var(--color-qe-text-muted)",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            &#x21bb;
          </button>
        </div>
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
        <NumericInput
          value={initialCapital}
          onChange={setInitialCapital}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="Max Loss ($)">
        <NumericInput
          value={maxLoss}
          onChange={setMaxLoss}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
      <SectionLabel>COST MODEL</SectionLabel>
      <ParamInput label="Slippage (bps)">
        <NumericInput
          value={slippageBps}
          onChange={(v) => setCosts(v, commissionBps)}
          disabled={disabled}
          className="w-full rounded px-1.5 py-1 text-[11px]"
          style={inputStyle}
        />
      </ParamInput>
      <ParamInput label="Commission (NT$/rt)">
        <NumericInput
          value={commissionFixed}
          onChange={setCommissionFixed}
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
              <NumericInput
                value={params[key] ?? 0}
                step={cfg.type === "int" ? 1 : 0.1}
                onChange={(v) => setParam(key, v)}
                disabled={disabled}
                className="w-full rounded px-1.5 py-1 text-[11px]"
                style={inputStyle}
              />
            </ParamInput>
          ))}
    </Sidebar>
  );
}
