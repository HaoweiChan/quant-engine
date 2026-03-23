interface StatCardProps {
  label: string;
  value: string;
  color: string;
  sub?: string;
}

export function StatCard({ label, value, color, sub }: StatCardProps) {
  return (
    <div
      className="flex-1 min-w-[90px] rounded-[5px] px-2.5 py-2"
      style={{
        background: "var(--color-qe-card)",
        border: "1px solid var(--color-qe-card-border)",
      }}
    >
      <div
        className="text-[7px] uppercase tracking-wider mb-0.5"
        style={{ color: "var(--color-qe-muted)", fontFamily: "var(--font-mono)" }}
      >
        {label}
      </div>
      <div
        className="text-[15px] font-bold"
        style={{ color, fontFamily: "var(--font-mono)" }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[7px] mt-0.5" style={{ color: "var(--color-qe-dim)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function StatRow({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-1.5 mb-3">{children}</div>;
}
