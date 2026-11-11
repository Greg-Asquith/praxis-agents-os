// apps/web/src/integrations/google_ads/components/research-keywords-table.tsx

import { use, useMemo, useState } from "react"
import { InfoIcon } from "lucide-react"

import { ConversationActionsContext } from "@/components/tool-ui/conversation-actions-context"
import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  buildAdGroupInstruction,
  themeTabs,
  type KeywordResearchResult,
} from "@/integrations/google_ads/lib/research-keywords"
import { getErrorMessage } from "@/lib/api/errors"
import { titleCaseToken } from "@/lib/format"

function columns(result: KeywordResearchResult): DataColumn[] {
  const money = { currencyCode: result.currency, kind: "currency", unit: "currency-units" } as const
  return [
    { key: "text", kind: "text", label: "Keyword", width: 220 },
    { key: "searches", kind: "number", label: "Avg Monthly Searches", width: 150 },
    { key: "trend", kind: "sparkline", label: "12-Month Trend" },
    { key: "competition", kind: "text", label: "Competition" },
    { ...money, key: "low_bid", label: "Low Bid" },
    { ...money, key: "high_bid", label: "High Bid" },
    ...(result.adGroups.length > 0
      ? [{ key: "ad_group", kind: "text", label: "Fits Ad Group" } as const]
      : []),
    { hidden: true, key: "themes_text", kind: "text", label: "Themes" },
  ]
}

/** Keyword ideas with theme tabs; selected rows start a governed turn that builds an ad group. */
export function ResearchKeywordsTable({ result }: { result: KeywordResearchResult }) {
  const sendInstruction = use(ConversationActionsContext)
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const adGroups = useMemo(
    () => new Map(result.adGroups.map((group) => [group.id, group.name])),
    [result.adGroups]
  )
  const rows = useMemo(
    () =>
      result.ideas.map((idea) => ({
        ad_group: idea.adGroupId ? (adGroups.get(idea.adGroupId) ?? null) : null,
        competition: idea.competition ? titleCaseToken(idea.competition.toLowerCase(), "") : null,
        high_bid: idea.highBid,
        low_bid: idea.lowBid,
        searches: idea.avgMonthlySearches,
        text: idea.text,
        themes: idea.themes,
        themes_text: idea.themes.join(", "),
        trend: idea.trend,
      })),
    [adGroups, result.ideas]
  )
  const tabs = useMemo(() => themeTabs(result.ideas), [result.ideas])
  const chosen = result.ideas.filter((idea) => selected.has(idea.text))

  async function handleBuild() {
    if (!sendInstruction) return
    setError(null)
    setSending(true)
    try {
      await sendInstruction(buildAdGroupInstruction(result, chosen))
      setSelected(new Set())
    } catch (sendError) {
      setError(getErrorMessage(sendError))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <DataTable
        columns={columns(result)}
        exportFilename={`google-ads-${result.accountId}-keyword-ideas.csv`}
        pageSize={25}
        rowNoun={["idea", "ideas"]}
        rows={rows}
        searchable
        selection={{
          actions: (
            <>
              {error ? <span className="text-destructive text-xs">{error}</span> : null}
              <Button
                disabled={!sendInstruction || sending}
                onClick={() => {
                  void handleBuild()
                }}
                size="sm"
                type="button"
              >
                Build Ad Group From {chosen.length.toLocaleString("en-GB")} Selected
              </Button>
            </>
          ),
          onChange: setSelected,
          rowId: (row) => String(row["text"]),
          selected,
        }}
        tabs={tabs}
        truncationNote={
          result.truncated
            ? `Google found ${result.totalIdeas.toLocaleString("en-GB")} ideas. These are the ${result.ideas.length.toLocaleString("en-GB")} with the most searches.`
            : null
        }
      />
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <InfoIcon aria-hidden className="size-3.5" />
        Searches and bids are Google&apos;s estimates for the last 12 months.
      </p>
    </div>
  )
}
