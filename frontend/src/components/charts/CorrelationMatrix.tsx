import { colors } from "@/lib/theme";


function shortName(slug: string): string {
  const parts = slug.split("/");
  return parts[parts.length - 1] || slug;
}

function cellColor(v: number): string {
  if (v >= 0.7) return colors.red;
  if (v >= 0.3) return colors.orange;
  if (v >= -0.3) return colors.green;
  return colors.blue;
}

export function CorrelationMatrix({ matrix, slugs }: { matrix: number[][]; slugs: string[] }) {
  return (
    <div className="flex flex-col items-start">
      <table className="text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr>
            <th />
            {slugs.map((s) => (
              <th key={s} className="px-3 py-1 font-normal text-center" style={{ color: colors.muted }} title={s}>{shortName(s)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, ri) => (
            <tr key={ri}>
              <td className="px-2 py-1 text-right" style={{ color: colors.muted }} title={slugs[ri]}>{shortName(slugs[ri])}</td>
              {row.map((v, ci) => (
                <td
                  key={ci}
                  className="px-3 py-1 text-center font-bold"
                  style={{ color: cellColor(v), background: `${cellColor(v)}10` }}
                >
                  {v.toFixed(3)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex gap-3 mt-2 text-[11px]" style={{ color: colors.dim }}>
        <span><span style={{ color: colors.red }}>■</span> High (≥0.7)</span>
        <span><span style={{ color: colors.orange }}>■</span> Moderate</span>
        <span><span style={{ color: colors.green }}>■</span> Low (±0.3)</span>
        <span><span style={{ color: colors.blue }}>■</span> Negative</span>
      </div>
    </div>
  );
}
