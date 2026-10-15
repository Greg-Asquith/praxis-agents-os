// apps/web/src/integrations/meta_ads/components/ad-set-entity.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { Loader2Icon, SearchIcon } from "lucide-react"
import { use, useState } from "react"

import {
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { FormField } from "@/integrations/meta_ads/components/campaign-controls"
import type { EntityReferenceValue } from "@/features/tools/types"
import { getErrorMessage } from "@/lib/api/errors"

// The create-ad-set tool declares each of these fields, so the card can look them up.
const TOOL = "meta_ads_create_ad_set"
const SEARCH_DEBOUNCE_MS = 300
const CURRENT = "current"

/** Picks the Page, pixel, or app a goal needs from what the ad account can use. */
export function EntityPicker({
  currentLabel,
  disabled,
  fieldKey,
  label,
  onChoose,
}: {
  currentLabel: string | null
  disabled: boolean
  fieldKey: "page" | "pixel" | "app"
  label: string
  onChoose: (value: EntityReferenceValue) => void
}) {
  const conversationId = use(ToolConversationContext)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      fieldKey,
      pageSize: 25,
      search: "",
      toolName: TOOL,
    }),
    enabled: conversationId !== null,
  })
  const choices = mergeEntityChoices([], results.data?.pages ?? [])
  const options = [
    ...(currentLabel ? [{ key: CURRENT, label: currentLabel }] : []),
    ...choices
      .filter((choice) => choice.label !== currentLabel)
      .map((choice) => ({ key: choice.identity.join("/"), label: choice.label })),
  ]
  return (
    <FormField label={label}>
      {(id) => (
        <>
          <Select<string>
            disabled={disabled || conversationId === null}
            onValueChange={(key) => {
              const chosen = choices.find((choice) => choice.identity.join("/") === key)
              if (chosen) onChoose(chosen.value)
            }}
            value={currentLabel ? CURRENT : null}
          >
            <SelectTrigger className="w-full" id={id}>
              <SelectValue placeholder={results.isPending ? "Loading" : `Choose a ${label}`} />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                {options.map((option) => (
                  <SelectItem key={option.key} label={option.label} value={option.key}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {results.isError ? (
            <p className="text-destructive text-sm">{getErrorMessage(results.error)}</p>
          ) : null}
        </>
      )}
    </FormField>
  )
}

/** A search box that lists matches from a lookup and hands the chosen one to `onChoose`. */
export function EntitySearch({
  disabled,
  entityKind,
  label,
  onChoose,
  placeholder,
}: {
  disabled: boolean
  entityKind: string
  label: string
  onChoose: (value: EntityReferenceValue) => void
  placeholder: string
}) {
  const conversationId = use(ToolConversationContext)
  const [input, setInput] = useState("")
  const search = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind,
      fieldKey: "targeting",
      pageSize: 10,
      search,
      toolName: TOOL,
    }),
    enabled: conversationId !== null && search !== "",
  })
  const choices = mergeEntityChoices([], results.data?.pages ?? [])
  const waiting = input.trim() !== "" && (input.trim() !== search || results.isFetching)
  return (
    <FormField label={label}>
      {(id) => (
        <>
          <div className="relative">
            <SearchIcon
              aria-hidden="true"
              className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
            />
            <Input
              className="pl-8 text-sm"
              disabled={disabled || conversationId === null}
              id={id}
              onChange={(event) => {
                setInput(event.currentTarget.value)
              }}
              placeholder={placeholder}
              value={input}
            />
          </div>
          {input.trim() === "" ? null : (
            <ul className="bg-background grid max-h-44 min-w-0 overflow-y-auto rounded-lg border">
              {waiting && choices.length === 0 ? (
                <li className="text-muted-foreground flex items-center gap-2 px-3 py-2 text-sm">
                  <Loader2Icon
                    aria-hidden="true"
                    className="size-4 animate-spin motion-reduce:animate-none"
                  />
                  Searching
                </li>
              ) : null}
              {results.isError ? (
                <li className="text-destructive px-3 py-2 text-sm">
                  {getErrorMessage(results.error)}
                </li>
              ) : null}
              {!waiting && !results.isError && choices.length === 0 ? (
                <li className="text-muted-foreground px-3 py-2 text-sm">Nothing found</li>
              ) : null}
              {choices.map((choice) => (
                <li key={choice.identity.join("/")}>
                  <Button
                    className="h-auto min-h-8 w-full justify-start gap-2 rounded-none py-1.5 text-left font-normal whitespace-normal"
                    onClick={() => {
                      onChoose(choice.value)
                      setInput("")
                    }}
                    type="button"
                    variant="ghost"
                  >
                    <span className="min-w-0 wrap-anywhere">{choice.label}</span>
                    {choice.description ? (
                      <span className="text-muted-foreground ml-auto shrink-0 truncate">
                        {choice.description}
                      </span>
                    ) : null}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </FormField>
  )
}
