import { Component, type ReactNode } from "react";
import { colors } from "@/lib/theme";

interface Props {
  children: ReactNode;
  fallbackLabel?: string;
}

interface State {
  error: Error | null;
}

export class ChartErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div
          className="rounded-[5px] p-3 text-[11px]"
          style={{
            border: `1px solid ${colors.red}`,
            color: colors.red,
            fontFamily: "var(--font-mono)",
            background: "rgba(255,82,82,0.05)",
          }}
        >
          {this.props.fallbackLabel ?? "Chart"} failed to render: {this.state.error.message}
        </div>
      );
    }
    return this.props.children;
  }
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            background: colors.bg,
            color: colors.text,
            fontFamily: "var(--font-mono)",
            gap: 16,
          }}
        >
          <div style={{ fontSize: 14, color: colors.red }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 11, color: colors.dim, maxWidth: 500, textAlign: "center" }}>
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: "8px 20px",
              fontSize: 12,
              border: `1px solid ${colors.cardBorder}`,
              borderRadius: 4,
              background: colors.card,
              color: colors.text,
              cursor: "pointer",
            }}
          >
            Try Again
          </button>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "8px 20px",
              fontSize: 12,
              border: `1px solid ${colors.cardBorder}`,
              borderRadius: 4,
              background: "transparent",
              color: colors.dim,
              cursor: "pointer",
            }}
          >
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
