// apps/web/src/components/ui/sparkline.tsx

const WIDTH = 72
const HEIGHT = 20

/** A small line of a series, scaled to its own range, or a dash without two numbers. */
export function Sparkline({ label, values }: { label: string; values: unknown }) {
  const series = Array.isArray(values)
    ? values.filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    : []
  if (series.length < 2) {
    return <span className="text-muted-foreground">—</span>
  }
  const low = Math.min(...series)
  const range = Math.max(...series) - low || 1
  const step = WIDTH / (series.length - 1)
  const points = series
    .map((value, index) => {
      const y = HEIGHT - 2 - ((value - low) / range) * (HEIGHT - 4)
      return `${(index * step).toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  return (
    <svg
      aria-label={`${label}: ${String(series[0])} to ${String(series.at(-1))}`}
      className="text-chart-1 block"
      height={HEIGHT}
      role="img"
      viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
      width={WIDTH}
    >
      <polyline fill="none" points={points} stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}
