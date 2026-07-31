// apps/web/src/features/knowledge/components/knowledge-search-panel.tsx

import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { LoaderCircleIcon, LockIcon, SearchIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { useKnowledgeSearchQuery } from "@/features/knowledge/api/search-knowledge"
import { SourceTypeBadge } from "@/features/knowledge/components/source-type-badge"
import { knowledgeContentText } from "@/features/knowledge/content"
import { getErrorMessage } from "@/lib/api/errors"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { cn } from "@/lib/utils"

const SEARCH_DEBOUNCE_MS = 300

export function KnowledgeSearchPanel() {
  const [input, setInput] = useState("")
  const trimmed = input.trim()
  const query = useDebouncedValue(trimmed, SEARCH_DEBOUNCE_MS)
  const search = useKnowledgeSearchQuery(query)
  const isSearching = trimmed !== "" && (trimmed !== query || search.isFetching)
  const showResults = trimmed !== "" && query !== ""

  return (
    <div className="flex flex-col gap-4">
      <div className="relative">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          aria-label="Search Knowledge Base"
          autoComplete="off"
          className="px-9"
          onChange={(event) => {
            setInput(event.currentTarget.value)
          }}
          placeholder="Search your knowledge base…"
          type="search"
          value={input}
        />
        {isSearching ? (
          <LoaderCircleIcon
            aria-hidden="true"
            className="text-muted-foreground absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin motion-reduce:animate-none"
          />
        ) : null}
      </div>
      {showResults && search.error ? (
        <Alert variant="destructive">
          <AlertTitle>Search failed</AlertTitle>
          <AlertDescription>{getErrorMessage(search.error)}</AlertDescription>
        </Alert>
      ) : null}
      {showResults && search.data?.mode === "lexical_fallback" ? (
        <p className="text-muted-foreground text-xs">
          Showing keyword matches while your documents finish processing.
        </p>
      ) : null}
      {showResults && !isSearching && search.data?.results.length === 0 ? (
        <EmptyState
          description="Try different words, or add more documents."
          icon={<SearchIcon className="size-5" />}
          size="compact"
          title="No matches"
        />
      ) : null}
      {showResults && search.data?.results.length ? (
        <ol
          aria-busy={isSearching}
          className={cn(
            "divide-border divide-y overflow-hidden rounded-lg border transition-opacity",
            isSearching && "opacity-50"
          )}
        >
          {search.data.results.map((result, index) => (
            <li className="flex min-w-0 flex-col gap-2 p-3" key={result.id}>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Link
                  className="min-w-0 truncate font-medium hover:underline"
                  params={{ documentId: result.document_id }}
                  to="/knowledge/$documentId"
                >
                  {result.title}
                </Link>
                <SourceTypeBadge sourceType={result.source_type} />
                {result.is_private ? (
                  <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                    <LockIcon className="size-3" />
                    Private
                  </span>
                ) : null}
                <span
                  className="text-muted-foreground ml-auto text-xs"
                  title="Results are ordered by combined keyword and meaning relevance."
                >
                  {index === 0 ? "Best match" : `Rank ${String(index + 1)}`}
                </span>
              </div>
              {result.context_line ? (
                <p className="text-muted-foreground text-xs">{result.context_line}</p>
              ) : null}
              <p className="text-foreground line-clamp-3 text-sm leading-6 whitespace-pre-wrap">
                {knowledgeContentText(result.content)}
              </p>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  )
}
