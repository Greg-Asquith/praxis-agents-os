// apps/web/src/integrations/google_ads/components/ad-group-combobox.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { use, useMemo, useState } from "react"

import {
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
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
import {
  parseAdGroupReference,
  type AdGroupReference,
} from "@/integrations/google_ads/lib/ad-groups"
import { isRecord } from "@/lib/guards"

const SEARCH_DEBOUNCE_MS = 300

export type ChosenAdGroup = {
  adGroup: AdGroupReference
  // The ad group's resource name.
  key: string
  // The reference as the search returned it, to send back unchanged.
  raw: Record<string, unknown>
}

function chosenAdGroup(value: unknown): ChosenAdGroup | null {
  const adGroup = parseAdGroupReference(value)
  if (!adGroup || !isRecord(value)) return null
  return {
    adGroup,
    key: `customers/${adGroup.customerId}/adGroups/${adGroup.adGroupId}`,
    raw: value,
  }
}

/** Chips for the chosen ad groups; typing searches the account's ad groups. */
export function AdGroupCombobox({
  chosen,
  disabled,
  fieldKey,
  onChange,
  toolName,
}: {
  chosen: readonly ChosenAdGroup[]
  disabled: boolean
  fieldKey: string
  onChange: (chosen: ChosenAdGroup[]) => void
  toolName: string
}) {
  const [input, setInput] = useState("")
  const search = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS)
  const conversationId = use(ToolConversationContext)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind: "google_ads_ad_group",
      fieldKey,
      pageSize: 10,
      search,
      toolName,
    }),
    enabled: search !== "" && !disabled && conversationId !== null,
  })
  const found = useMemo(
    () =>
      mergeEntityChoices([], results.data?.pages ?? []).flatMap((choice) => {
        const item = chosenAdGroup(choice.value)
        return item ? [item] : []
      }),
    [results.data]
  )
  return (
    <Combobox<ChosenAdGroup, true>
      disabled={disabled}
      filter={null}
      inputValue={input}
      isItemEqualToValue={(left, right) => left.key === right.key}
      itemToStringLabel={(item) => item.adGroup.label}
      items={found}
      multiple
      onInputValueChange={setInput}
      onOpenChange={(open) => {
        if (!open) setInput("")
      }}
      onValueChange={(next) => {
        onChange(next)
        setInput("")
      }}
      // Closed until the operator types, so the card doesn't open on a long list.
      open={input.trim() !== ""}
      value={[...chosen]}
    >
      <ComboboxInputGroup className="min-h-9">
        <ComboboxChips className="py-1">
          {chosen.map((item) => (
            <ComboboxChip key={item.key}>
              <span className="truncate">{item.adGroup.label}</span>
              <ComboboxChipRemove aria-label={`Remove ${item.adGroup.label}`} />
            </ComboboxChip>
          ))}
          <ComboboxInput
            aria-label="Search ad groups"
            placeholder={chosen.length === 0 ? "Search ad groups" : "Add another…"}
          />
        </ComboboxChips>
      </ComboboxInputGroup>
      <ComboboxContent>
        {found.map((item) => (
          <ComboboxItem key={item.key} value={item}>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">{item.adGroup.label}</span>
              {item.adGroup.campaignLabel ? (
                <span className="text-muted-foreground line-clamp-1 text-xs">
                  {item.adGroup.campaignLabel}
                </span>
              ) : null}
            </span>
          </ComboboxItem>
        ))}
        <ComboboxEmpty>
          {results.isFetching || search !== input.trim() ? "Searching…" : "No matches"}
        </ComboboxEmpty>
      </ComboboxContent>
    </Combobox>
  )
}
