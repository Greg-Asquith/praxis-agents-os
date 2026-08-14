// apps/web/src/components/tool-ui/entity-field-input.tsx

import { useEffect, useMemo, useState } from "react"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { LoaderCircleIcon } from "lucide-react"

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
  ComboboxTrigger,
} from "@/components/ui/combobox"
import { Button } from "@/components/ui/button"
import {
  entityReferenceHydrationQueryOptions,
  entityReferenceKey,
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import type { ApprovalField } from "@/components/tool-ui/approval-types"
import type { EntityChoice, EntityReferenceValue } from "@/features/tools/types"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { getErrorMessage } from "@/lib/api/errors"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

const SEARCH_DEBOUNCE_MS = 250

export function EntityFieldInput({
  conversationId,
  dependentArgs,
  disabled,
  field,
  id,
  onChange,
  onValidityChange,
  toolName,
  value,
}: {
  conversationId: string
  dependentArgs: Record<string, unknown>
  disabled: boolean
  field: ApprovalField
  id: string
  onChange: (value: EntityReferenceValue | EntityReferenceValue[]) => void
  onValidityChange: (key: string, valid: boolean) => void
  toolName: string
  value: unknown
}) {
  const multiple = field.format === "entity_list"
  const exactValues = useMemo(() => referenceValues(value, multiple), [multiple, value])
  const invalidShape = exactValues === null
  const missingSelection = !invalidShape && !field.secondary && exactValues.length === 0
  const hydration = useQuery({
    ...entityReferenceHydrationQueryOptions({
      conversationId,
      dependentArgs,
      exactValues: exactValues ?? [],
      fieldKey: field.key,
      toolName,
    }),
    enabled: !invalidShape && exactValues.length > 0,
  })
  const [searchInput, setSearchInput] = useState("")
  const [open, setOpen] = useState(false)
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId,
      dependentArgs,
      fieldKey: field.key,
      search,
      toolName,
    }),
    enabled: open,
  })
  const choices = useMemo(
    () => mergeEntityChoices(hydration.data?.choices ?? [], results.data?.pages ?? []),
    [hydration.data?.choices, results.data?.pages]
  )
  const selected = useMemo(() => {
    const hydrated = hydration.data?.choices ?? []
    return hydrated.length === (exactValues ?? []).length ? hydrated : []
  }, [exactValues, hydration.data?.choices])
  const unresolved =
    !invalidShape &&
    exactValues.length > 0 &&
    !hydration.isPending &&
    !hydration.isFetching &&
    (hydration.isError || selected.length !== exactValues.length)
  const unavailable = invalidShape || unresolved
  const checking =
    !invalidShape && exactValues.length > 0 && (hydration.isPending || hydration.isFetching)
  const valid = !checking && !unavailable && !missingSelection

  useEffect(() => {
    onValidityChange(field.key, valid)
  }, [field.key, onValidityChange, valid])

  useEffect(() => {
    return () => {
      onValidityChange(field.key, true)
    }
  }, [field.key, onValidityChange])

  const rootProps = {
    autoHighlight: true,
    disabled,
    filter: null,
    isItemEqualToValue: (left: EntityChoice, right: EntityChoice) =>
      referenceKey(left) === referenceKey(right),
    itemToStringLabel: (choice: EntityChoice) => choice.label,
    items: choices,
    onInputValueChange: setSearchInput,
    onOpenChange: (nextOpen: boolean) => {
      setOpen(nextOpen)
      if (!nextOpen) {
        setSearchInput("")
      }
    },
  }

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {multiple ? (
        <Combobox<EntityChoice, true>
          {...rootProps}
          multiple
          onValueChange={(nextChoices) => {
            onChange(nextChoices.map((choice) => choice.value))
          }}
          value={selected}
        >
          <ComboboxInputGroup
            className={cn((unavailable || missingSelection) && "border-destructive/50")}
          >
            <ComboboxChips>
              {selected.map((choice) => (
                <ComboboxChip key={referenceKey(choice)}>
                  <span className="truncate">{choice.label}</span>
                  <ComboboxChipRemove aria-label={`Remove ${choice.label}`} />
                </ComboboxChip>
              ))}
              <ComboboxInput aria-label={`Search ${field.label}`} id={id} placeholder="Search…" />
            </ComboboxChips>
            <ComboboxTrigger aria-label={`Open ${field.label}`} />
          </ComboboxInputGroup>
          <ChoiceContent choices={choices} results={results} />
        </Combobox>
      ) : (
        <Combobox<EntityChoice>
          {...rootProps}
          onValueChange={(nextChoice) => {
            if (nextChoice) {
              onChange(nextChoice.value)
            }
          }}
          value={selected[0] ?? null}
        >
          <ComboboxInputGroup
            className={cn((unavailable || missingSelection) && "border-destructive/50")}
          >
            <ComboboxInput aria-label={`Search ${field.label}`} id={id} placeholder="Search…" />
            <ComboboxTrigger aria-label={`Open ${field.label}`} />
          </ComboboxInputGroup>
          <ChoiceContent choices={choices} results={results} />
        </Combobox>
      )}
      {checking ? (
        <p className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
          <LoaderCircleIcon className="size-3 animate-spin motion-reduce:animate-none" />
          Checking target…
        </p>
      ) : unavailable ? (
        <p className="text-destructive text-xs">
          {hydration.isError
            ? getErrorMessage(hydration.error)
            : "Target unavailable. Choose another target before continuing."}
        </p>
      ) : missingSelection ? (
        <p className="text-destructive text-xs">
          {multiple ? "Choose at least one target to continue." : "Choose a target to continue."}
        </p>
      ) : null}
    </div>
  )
}

function ChoiceContent({
  choices,
  results,
}: {
  choices: EntityChoice[]
  results: ReturnType<typeof useInfiniteQuery>
}) {
  return (
    <ComboboxContent>
      {choices.map((choice) => (
        <ComboboxItem key={referenceKey(choice)} value={choice}>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-medium">{choice.label}</span>
            {choice.description || choice.scope_label ? (
              <span className="text-muted-foreground line-clamp-2 text-xs">
                {[choice.description, choice.scope_label].filter(Boolean).join(" · ")}
              </span>
            ) : null}
          </span>
        </ComboboxItem>
      ))}
      <ComboboxEmpty>
        {results.isFetching ? "Searching…" : results.isError ? "Search unavailable" : "No matches"}
      </ComboboxEmpty>
      {results.hasNextPage ? (
        <Button
          className="mt-1 w-full"
          disabled={results.isFetchingNextPage}
          onClick={() => void results.fetchNextPage()}
          size="sm"
          type="button"
          variant="ghost"
        >
          {results.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      ) : null}
    </ComboboxContent>
  )
}

function referenceValues(value: unknown, multiple: boolean): EntityReferenceValue[] | null {
  if (multiple) {
    return Array.isArray(value) && value.every(isRecord) ? value : null
  }
  if (value === null || value === undefined) {
    return []
  }
  return isRecord(value) ? [value] : null
}

const referenceKey = entityReferenceKey
