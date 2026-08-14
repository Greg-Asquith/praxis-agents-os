// apps/web/src/features/usage/components/usage-token-stats.tsx

import { Stat, StatGroup } from "@/components/ui/stat"
import { formatTokenCount } from "@/features/usage/format"
import type { TokenCounts } from "@/features/usage/types"

export function UsageTokenStats({ tokens }: { tokens: TokenCounts }) {
  return (
    <StatGroup className="border-border border-y py-5 sm:py-5">
      <Stat
        footnote="New instructions and context sent to AI models."
        label="Input"
        value={formatTokenCount(tokens.input)}
      />
      <Stat
        footnote="Repeated context billed at a lower rate."
        label="Cached input"
        value={formatTokenCount(tokens.cache_read)}
      />
      <Stat
        footnote="Context newly stored for later reuse."
        label="Cache writes"
        value={formatTokenCount(tokens.cache_write)}
      />
      <Stat
        footnote="Text and tool instructions produced by AI models."
        label="Output"
        value={formatTokenCount(tokens.output)}
      />
    </StatGroup>
  )
}
