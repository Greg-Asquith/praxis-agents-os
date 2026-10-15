// apps/web/src/integrations/meta_ads/components/ad-set-picker.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { use, useState } from "react"

import {
  entityReferenceSearchQueryOptions,
  entitySearchEnabled,
} from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { Button } from "@/components/ui/button"
import {
  Combobox,
  ComboboxChip,
  ComboboxChipRemove,
  ComboboxChips,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxInputGroup,
  ComboboxItem,
} from "@/components/ui/combobox"
import type { EntityChoice } from "@/features/tools/types"
import { adSetName, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { getErrorMessage } from "@/lib/api/errors"
import { isRecord } from "@/lib/guards"

// The create-ads tool declares the ad set kind on its ads field, so the card can search it.
const LOOKUP = { toolName: "meta_ads_create_ads", fieldKey: "ads", dependentArgs: {} } as const
const SEARCH_DEBOUNCE_MS = 250

function adSetId(choice: EntityChoice): string {
  return String(choice.value["adset_id"])
}

/** The ad sets an ad is created in, as chips; searching adds another. */
export function AdSetPicker({
  args,
  disabled,
  id,
  index,
  onChange,
}: {
  args: CreateAdsArgs
  disabled: boolean
  id: string
  index: number
  onChange: (adSets: Record<string, unknown>[]) => void
}) {
  const conversationId = use(ToolConversationContext)
  const [searchInput, setSearchInput] = useState("")
  const [open, setOpen] = useState(false)
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS)
  const references = args.rawAds[index]?.["ad_sets"]
  const selected: EntityChoice[] = (Array.isArray(references) ? references : [])
    .filter(isRecord)
    .map((value) => ({
      identity: ["meta_ads_ad_set", String(value["adset_id"])],
      value,
      label: adSetName(args, String(value["adset_id"])),
    }))
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      ...LOOKUP,
      conversationId: conversationId ?? "",
      entityKind: "meta_ads_ad_set",
      search,
    }),
    enabled: conversationId !== null && entitySearchEnabled({ disabled, open, search }),
  })
  const chosen = new Set(selected.map(adSetId))
  const found = (results.data?.pages ?? []).flatMap((page) => page.choices)
  const items = [...selected, ...found.filter((choice) => !chosen.has(adSetId(choice)))]
  return (
    <Combobox<EntityChoice, true>
      autoHighlight
      disabled={disabled || conversationId === null}
      filter={null}
      isItemEqualToValue={(left, right) => adSetId(left) === adSetId(right)}
      items={items}
      itemToStringLabel={(choice) => choice.label}
      multiple
      onInputValueChange={setSearchInput}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setSearchInput("")
      }}
      onValueChange={(next) => {
        onChange(next.map((choice) => choice.value))
      }}
      value={selected}
    >
      <ComboboxInputGroup>
        <ComboboxChips>
          {selected.map((choice) => (
            <ComboboxChip key={adSetId(choice)} className="h-8">
              <span className="truncate">{choice.label}</span>
              <ComboboxChipRemove
                aria-label={`Remove ${choice.label}`}
                className="-mr-1 p-1.5"
                disabled={selected.length <= 1}
              />
            </ComboboxChip>
          ))}
          <ComboboxInput aria-label="Add another ad set" id={id} placeholder="Add another ad set" />
        </ComboboxChips>
      </ComboboxInputGroup>
      <ComboboxContent>
        {items.map((choice) => (
          <ComboboxItem key={adSetId(choice)} value={choice}>
            <span className="truncate font-medium">{choice.label}</span>
          </ComboboxItem>
        ))}
        <ComboboxEmpty>
          {results.isFetching ? "Searching" : results.isError ? "Search unavailable" : "No matches"}
        </ComboboxEmpty>
        {results.isError ? (
          <p className="text-destructive px-2.5 py-2 text-sm">{getErrorMessage(results.error)}</p>
        ) : null}
        {results.hasNextPage ? (
          <Button
            className="mt-1 w-full"
            disabled={results.isFetchingNextPage}
            onClick={() => {
              void results.fetchNextPage()
            }}
            type="button"
            variant="ghost"
          >
            {results.isFetchingNextPage ? "Loading" : "Show More"}
          </Button>
        ) : null}
      </ComboboxContent>
    </Combobox>
  )
}
