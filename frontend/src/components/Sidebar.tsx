interface SidebarProps {
  children: React.ReactNode;
}

export function Sidebar({ children }: SidebarProps) {
  return (
    <div
      className="w-[234px] min-w-[234px] shrink-0 overflow-y-auto px-3 py-2.5"
      style={{
        background: "var(--color-qe-sidebar)",
        borderRight: "1px solid var(--color-qe-card-border)",
      }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[10px] uppercase tracking-[1px] font-bold mb-2"
      style={{ color: "var(--color-qe-muted)", fontFamily: "var(--font-mono)" }}
    >
      {children}
    </div>
  );
}

export function ParamInput({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div
        className="text-[11px] mb-0.5"
        style={{ color: "var(--color-qe-dim)", fontFamily: "var(--font-mono)" }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}
