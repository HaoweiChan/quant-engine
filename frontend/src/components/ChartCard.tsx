interface ChartCardProps {
  title: string;
  children: React.ReactNode;
}

export function ChartCard({ title, children }: ChartCardProps) {
  return (
    <div
      className="rounded-md p-3 pb-2 mb-2.5"
      style={{
        background: "var(--color-qe-card)",
        border: "1px solid var(--color-qe-card-border)",
      }}
    >
      <div
        className="text-[9px] tracking-wider mb-1.5 pl-1"
        style={{ color: "var(--color-qe-muted)", fontFamily: "var(--font-mono)" }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}
