/** Dark terminal color palette — matches src/dashboard/theme.py */
export const colors = {
  bg: "#0F1117",
  sidebar: "#141721",
  card: "#1A1D28",
  cardBorder: "#2A2D3E",
  input: "#1E2130",
  inputBorder: "#353849",
  green: "#69f0ae",
  red: "#ff5252",
  blue: "#5a8af2",
  cyan: "#4fc3f7",
  purple: "#ce93d8",
  gold: "#ffd54f",
  orange: "#ff8a65",
  lightBlue: "#81d4fa",
  muted: "#8B8FA3",
  dim: "#6B7280",
  text: "#E0E0E0",
  grid: "#252838",
} as const;

export const fonts = {
  mono: "'JetBrains Mono', monospace",
  sans: "'IBM Plex Sans', system-ui, sans-serif",
  serif: "'IBM Plex Serif', serif",
} as const;

/** Value color based on sign */
export function pnlColor(value: number): string {
  return value >= 0 ? colors.green : colors.red;
}
