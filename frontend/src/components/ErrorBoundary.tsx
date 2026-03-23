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
