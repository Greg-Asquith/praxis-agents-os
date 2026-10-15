// apps/web/src/integrations/meta_ads/components/entity-search.tsx

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
import type { EntityChoice } from "@/features/tools/types"
import { getErrorMessage } from "@/lib/api/errors"

const SEARCH_DEBOUNCE_MS = 300

/** Searches the tool's entity lookup and hands back the chosen reference unchanged. */
export function EntitySearch({
  disabled = false,
  entityKind,
  fieldKey,
  isTaken,
  label,
  onChoose,
  placeholder = "Search by name",
  searchRequired = false,
  toolName,
}: {
  disabled?: boolean
  entityKind?: string
  fieldKey: string
  // True for a choice already in use where this one would go.
  isTaken?: (choice: EntityChoice) => boolean
  label: string
  onChoose: (choice: EntityChoice) => void
  placeholder?: string
  // Lists nothing until the operator types, for lookups that need a search term.
  searchRequired?: boolean
  toolName: string
}) {
  const conversationId = use(ToolConversationContext)
  const [input, setInput] = useState("")
  const search = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      conversationId: conversationId ?? "",
      dependentArgs: {},
      entityKind,
      fieldKey,
      search,
      toolName,
    }),
    enabled: conversationId !== null && !(searchRequired && search === ""),
  })
  if (conversationId === null) {
    return <p className="text-muted-foreground text-sm">Open the conversation to search.</p>
  }
  const choices = mergeEntityChoices([], results.data?.pages ?? [])
  const idle = searchRequired && input.trim() === ""
  return (
    <div className="grid min-w-0 gap-2">
      <div className="relative">
        <SearchIcon
          aria-hidden="true"
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
        />
        <Input
          aria-label={label}
          className="pl-8"
          disabled={disabled}
          onChange={(event) => {
            setInput(event.currentTarget.value)
          }}
          placeholder={placeholder}
          value={input}
        />
      </div>
      {idle ? null : results.isPending ? (
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2Icon
            aria-hidden="true"
            className="size-4 animate-spin motion-reduce:animate-none"
          />
          Loading
        </p>
      ) : results.isError ? (
        <p className="text-destructive text-sm">{getErrorMessage(results.error)}</p>
      ) : choices.length === 0 ? (
        <p className="text-muted-foreground text-sm">Nothing found.</p>
      ) : (
        <ul className="max-h-48 divide-y overflow-y-auto rounded-lg border">
          {choices.map((choice) => {
            const taken = isTaken?.(choice) ?? false
            return (
              <li key={choice.identity.join(":")}>
                <button
                  className="hover:bg-muted/60 focus-visible:ring-ring/50 grid min-h-9 w-full cursor-pointer gap-0.5 px-3 py-1.5 text-left text-sm outline-none focus-visible:ring-3 focus-visible:ring-inset disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={disabled || taken}
                  onClick={() => {
                    onChoose(choice)
                  }}
                  type="button"
                >
                  <span className="font-medium wrap-anywhere">{choice.label}</span>
                  <span className="text-muted-foreground wrap-anywhere">
                    {taken
                      ? "Already added"
                      : [choice.description, choice.scope_label].filter(Boolean).join(" · ")}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {!idle && results.hasNextPage ? (
        <Button
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
    </div>
  )
}
