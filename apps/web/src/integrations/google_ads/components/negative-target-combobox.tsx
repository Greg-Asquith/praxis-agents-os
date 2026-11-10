// apps/web/src/integrations/google_ads/components/negative-target-combobox.tsx

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
  TARGET_ENTITY_KINDS,
  TARGET_KIND_LABELS,
  targetEntry,
  type NegativeEntry,
  type SearchableTargetKind,
} from "@/integrations/google_ads/lib/negative-keywords"

const SEARCH_DEBOUNCE_MS = 300

type TargetChoice = { detail: string; entry: NegativeEntry; label: string }

/** Chips for the chosen targets; typing searches campaigns, ad groups, and lists at once. */
export function NegativeTargetCombobox({
  disabled,
  onChange,
  targets,
  toolName,
}: {
  disabled: boolean
  onChange: (targets: NegativeEntry[]) => void
  targets: readonly NegativeEntry[]
  toolName: string
}) {
  const [input, setInput] = useState("")
  const search = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS)
  const searching = search !== "" && !disabled
  const campaigns = useTargetSearch("campaign", search, searching, toolName)
  const adGroups = useTargetSearch("ad_group", search, searching, toolName)
  const lists = useTargetSearch("list", search, searching, toolName)
  const selected = useMemo(
    () =>
      targets.map((entry) => ({
        detail: TARGET_KIND_LABELS[entry.kind],
        entry,
        label: entry.label,
      })),
    [targets]
  )
  const found = [...campaigns.choices, ...adGroups.choices, ...lists.choices]
  const pending = campaigns.pending || adGroups.pending || lists.pending
  return (
    <Combobox<TargetChoice, true>
      disabled={disabled}
      filter={null}
      inputValue={input}
      isItemEqualToValue={(left, right) => left.entry.key === right.entry.key}
      itemToStringLabel={(choice) => choice.label}
      items={found}
      multiple
      onInputValueChange={setInput}
      onOpenChange={(open) => {
        if (!open) setInput("")
      }}
      onValueChange={(next) => {
        onChange(next.map((choice) => choice.entry))
        setInput("")
      }}
      // Closed until the operator types, so the card doesn't open on a long list.
      open={input.trim() !== ""}
      value={selected}
    >
      <ComboboxInputGroup className="min-h-9">
        <ComboboxChips className="py-1">
          {selected.map((choice) => (
            <ComboboxChip key={choice.entry.key}>
              <span className="truncate">{choice.label}</span>
              <span className="text-muted-foreground">{choice.detail}</span>
              <ComboboxChipRemove aria-label={`Remove ${choice.label}`} />
            </ComboboxChip>
          ))}
          <ComboboxInput
            aria-label="Search campaigns, ad groups, and lists"
            placeholder={
              selected.length === 0 ? "Search campaigns, ad groups, and lists" : "Add another…"
            }
          />
        </ComboboxChips>
      </ComboboxInputGroup>
      <ComboboxContent>
        {found.map((choice) => (
          <ComboboxItem key={choice.entry.key} value={choice}>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">{choice.label}</span>
              <span className="text-muted-foreground line-clamp-1 text-xs">{choice.detail}</span>
            </span>
          </ComboboxItem>
        ))}
        <ComboboxEmpty>
          {pending || search !== input.trim() ? "Searching…" : "No matches"}
        </ComboboxEmpty>
      </ComboboxContent>
    </Combobox>
  )
}

function useTargetSearch(
  kind: SearchableTargetKind,
  search: string,
  enabled: boolean,
  toolName: string
): { choices: TargetChoice[]; pending: boolean } {
  const conversationId = use(ToolConversationContext)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind: TARGET_ENTITY_KINDS[kind],
      fieldKey: "entries",
      pageSize: 10,
      search,
      toolName,
    }),
    enabled: enabled && conversationId !== null,
  })
  const choices = mergeEntityChoices([], results.data?.pages ?? []).flatMap((choice) => {
    const entry = targetEntry(kind, choice.value)
    if (!entry) return []
    const detail = [TARGET_KIND_LABELS[kind], choice.description].filter(Boolean).join(" · ")
    return [{ detail, entry, label: choice.label }]
  })
  return { choices, pending: enabled && results.isFetching }
}
