// apps/web/src/integrations/meta_ads/components/ads-list.tsx

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { PaginationControls, paginateItems } from "@/components/ui/pagination-controls"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CheckMark } from "@/integrations/meta_ads/components/field-notes"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import {
  adSetName,
  FORMAT_LABELS,
  type CreateAdsArgs,
} from "@/integrations/meta_ads/lib/create-ads-args"
import type { AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 10
// Filters only earn their space once there are more ads than fit on a glance.
const FILTER_THRESHOLD = 6
const ALL_AD_SETS = "all"

/** Every ad in the request; choosing one opens it in the editor below. */
export function AdsList({
  args,
  rows,
  selected,
  onSelect,
}: {
  args: CreateAdsArgs
  rows: AdRow[]
  selected: number
  onSelect: (index: number) => void
}) {
  const [offset, setOffset] = useState(
    () =>
      Math.floor(
        Math.max(
          0,
          rows.findIndex((row) => row.ad.index === selected)
        ) / PAGE_SIZE
      ) * PAGE_SIZE
  )
  const [adSetFilter, setAdSetFilter] = useState(ALL_AD_SETS)
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const visible = rows.filter(
    (row) =>
      (!flaggedOnly || row.check !== "ready") &&
      (adSetFilter === ALL_AD_SETS || row.ad.adSetIds.includes(adSetFilter))
  )
  const page = paginateItems(visible, offset, PAGE_SIZE)
  const flagged = rows.filter((row) => row.check !== "ready").length
  const filters = rows.length > FILTER_THRESHOLD
  return (
    <section aria-label="Ads to create" className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {String(rows.length)} {pluralize(rows.length, "Ad")}
        </p>
        {filters ? (
          <div className="flex flex-wrap items-center gap-2">
            {args.adSets.size > 1 ? (
              <Select<string>
                onValueChange={(value) => {
                  setAdSetFilter(value ?? ALL_AD_SETS)
                  setOffset(0)
                }}
                value={adSetFilter}
              >
                <SelectTrigger aria-label="Show ads in" className="w-48" size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  <SelectGroup>
                    <SelectItem label="All ad sets" value={ALL_AD_SETS}>
                      All ad sets
                    </SelectItem>
                    {[...args.adSets.values()].map((adSet) => (
                      <SelectItem key={adSet.id} label={adSet.name} value={adSet.id}>
                        {adSet.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : null}
            {flagged > 0 ? (
              <Button
                aria-pressed={flaggedOnly}
                onClick={() => {
                  setFlaggedOnly((value) => !value)
                  setOffset(0)
                }}
                size="sm"
                type="button"
                variant={flaggedOnly ? "secondary" : "outline"}
              >
                Needs Attention ({String(flagged)})
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      <ul className="divide-y overflow-hidden rounded-lg border">
        {page.items.map((row) => {
          const current = row.ad.index === selected
          const media = row.ad.media ?? row.ad.cards[0]?.media ?? null
          const adSets = row.ad.adSetIds.map((id) => adSetName(args, id))
          return (
            <li key={row.ad.index}>
              <button
                aria-current={current ? "true" : undefined}
                className={cn(
                  "hover:bg-muted/50 focus-visible:ring-ring/50 flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset",
                  current && "bg-muted/70 hover:bg-muted/70"
                )}
                onClick={() => {
                  onSelect(row.ad.index)
                }}
                type="button"
              >
                <MediaFrame className="size-10 shrink-0 rounded-md" media={media} shape="square" />
                <span className="grid min-w-0 flex-1">
                  <span className="truncate text-sm font-medium">
                    {row.ad.name || "Unnamed ad"}
                  </span>
                  <span className="text-muted-foreground truncate text-xs">
                    {[
                      FORMAT_LABELS[row.ad.format],
                      row.ad.format === "carousel" ? `${String(row.ad.cards.length)} cards` : null,
                      adSets.join(", "),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <CheckMark check={row.check} checks={row.checks} />
              </button>
            </li>
          )
        })}
        {page.items.length === 0 ? (
          <li className="text-muted-foreground px-3 py-4 text-center text-sm">
            No ads match these filters.
          </li>
        ) : null}
      </ul>
      {visible.length > PAGE_SIZE ? (
        <PaginationControls
          ariaLabel="Ads pages"
          limit={PAGE_SIZE}
          offset={page.offset}
          onPageChange={setOffset}
          total={visible.length}
        />
      ) : null}
    </section>
  )
}
