// apps/web/src/integrations/google_ads/components/search-term-target-combobox.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { use, useState } from "react"

import {
  entityReferenceSearchQueryOptions,
  entitySearchEnabled,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxInputGroup,
  ComboboxItem,
  ComboboxTrigger,
} from "@/components/ui/combobox"
import {
  searchedTarget,
  type TargetOption,
  type TargetSearchKind,
} from "@/integrations/google_ads/lib/search-terms"

const TOOL = "google_ads_optimise_search_terms"
const SEARCH_DEBOUNCE_MS = 250
const ENTITY_KINDS: Record<TargetSearchKind, string> = {
  ad_group: "google_ads_ad_group",
  list: "google_ads_shared_set",
}

/** Picks a target from the quick choices, or by searching lists or ad groups in the account. */
export function SearchTermTargetCombobox({
  className,
  customerId,
  disabled,
  label,
  onChoose,
  options,
  placeholder,
  searchKind,
  value,
}: {
  className?: string
  customerId: string
  disabled: boolean
  label: string
  onChoose: (target: TargetOption) => void
  options: readonly TargetOption[]
  placeholder: string
  searchKind: TargetSearchKind
  value: TargetOption | null
}) {
  const conversationId = use(ToolConversationContext)
  const [input, setInput] = useState("")
  const [open, setOpen] = useState(false)
  const search = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind: ENTITY_KINDS[searchKind],
      fieldKey: "decisions",
      pageSize: 10,
      search,
      toolName: TOOL,
    }),
    enabled: conversationId !== null && entitySearchEnabled({ disabled, open, search }),
  })
  const query = input.trim().toLowerCase()
  const quick = options.filter((option) => !query || option.label.toLowerCase().includes(query))
  const held = new Set(quick.map((option) => option.value))
  const found = query
    ? mergeEntityChoices([], results.data?.pages ?? []).flatMap((choice) => {
        const option = searchedTarget(searchKind, choice.value, choice.label, customerId)
        return option && !held.has(option.value) ? [option] : []
      })
    : []
  const items = [...quick, ...found]
  const searchNoun = searchKind === "list" ? "negative keyword lists" : "ad groups"
  return (
    <Combobox<TargetOption>
      autoHighlight
      disabled={disabled}
      filter={null}
      inputValue={input}
      isItemEqualToValue={(left, right) => left.value === right.value}
      items={items}
      itemToStringLabel={(option) => option.label}
      onInputValueChange={setInput}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setInput("")
      }}
      onValueChange={(next) => {
        if (next && next.value !== value?.value) onChoose(next)
        setInput("")
      }}
      value={value}
    >
      <ComboboxInputGroup className={className ?? "h-7 min-h-7 w-full pr-1"}>
        <ComboboxInput
          aria-label={label}
          className="placeholder:text-foreground truncate py-0 text-sm"
          // The current target shows until the operator types a search.
          placeholder={value?.label ?? placeholder}
        />
        <ComboboxTrigger aria-label={`Show choices for ${label}`} />
      </ComboboxInputGroup>
      <ComboboxContent className="w-80">
        {items.map((option) => (
          <ComboboxItem key={option.value} value={option}>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="font-medium wrap-anywhere">{option.label}</span>
              <span className="text-muted-foreground text-xs">{option.detail}</span>
            </span>
          </ComboboxItem>
        ))}
        <ComboboxEmpty>
          {results.isFetching || search !== input.trim() ? "Searching…" : "No matches"}
        </ComboboxEmpty>
        {!query ? (
          <p className="text-muted-foreground px-2.5 py-1.5 text-xs">
            Type to search {searchNoun}.
          </p>
        ) : null}
      </ComboboxContent>
    </Combobox>
  )
}
