// apps/web/src/features/usage/components/cost-quality-panel.tsx

import { microLabelClass } from "@/components/ui/stat"
import type { PricingCoverage } from "@/features/usage/types"
import { formatTokenCount } from "@/features/usage/format"

export function CostQualityPanel({ coverage }: { coverage: PricingCoverage }) {
  return (
    <aside className="border-border rounded-xl border p-4" aria-labelledby="cost-quality-heading">
      <p className={microLabelClass}>Estimate quality</p>
      <h3 className="font-heading mt-2 text-lg font-medium" id="cost-quality-heading">
        {formatPercent(coverage.token_coverage_percent)} of tokens priced
      </h3>
      <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
        Known models use public API rates. Unknown or custom models remain visibly unpriced.
      </p>
      <dl className="border-border mt-4 grid grid-cols-2 gap-4 border-t pt-4 text-sm">
        <CoverageStat label="Priced tokens" value={formatTokenCount(coverage.priced_tokens)} />
        <CoverageStat label="Unpriced tokens" value={formatTokenCount(coverage.unpriced_tokens)} />
        <CoverageStat label="Priced requests" value={formatTokenCount(coverage.priced_requests)} />
        <CoverageStat
          label="Unpriced requests"
          value={formatTokenCount(coverage.unpriced_requests)}
        />
        {coverage.priced_image_generations + coverage.unpriced_image_generations > 0 ? (
          <>
            <CoverageStat
              label="Priced image outputs"
              value={formatTokenCount(coverage.priced_image_generations)}
            />
            <CoverageStat
              label="Incomplete image outputs"
              value={formatTokenCount(coverage.unpriced_image_generations)}
            />
          </>
        ) : null}
      </dl>
      {coverage.priced_image_generations + coverage.unpriced_image_generations > 0 ? (
        <p className="text-muted-foreground mt-4 text-xs leading-relaxed">
          These figures are estimates based on publicly available pricing information and token
          counts returned from providers. It may not match your bill exactly, especially for web
          search/image generation.
        </p>
      ) : null}
    </aside>
  )
}

function CoverageStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 font-medium tabular-nums">{value}</dd>
    </div>
  )
}

function formatPercent(value: string) {
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Number(value))}%`
}
