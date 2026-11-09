// apps/web/src/integrations/google_ads/components/location-paste.tsx

import { use, useId, useState } from "react"

import { lookupEntityReferences } from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { EntityChoice } from "@/features/tools/types"
import { pasteBatches } from "@/integrations/google_ads/lib/update-targeting"
import { getErrorMessage } from "@/lib/api/errors"

type Found = { found: number; lines: number; missing: string[] }

/** Finds pasted places, one per line, in Google's list; lines Google doesn't know are counted. */
export function LocationPaste({
  disabled,
  onFound,
  toolName,
}: {
  disabled: boolean
  onFound: (choices: EntityChoice[]) => void
  toolName: string
}) {
  const id = useId()
  const conversationId = use(ToolConversationContext)
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [found, setFound] = useState<Found | null>(null)

  const find = async () => {
    const lines = [...new Set(text.split("\n").map((line) => line.trim()))].filter(Boolean)
    setBusy(true)
    setError(null)
    try {
      const choices: EntityChoice[] = []
      // One at a time, because the route's rate limit is shared with the card's other lookups.
      for (const batch of pasteBatches(lines)) {
        const page = await lookupEntityReferences({
          conversationId: conversationId ?? "",
          dependentArgs: {},
          entityKind: "google_ads_location",
          fieldKey: "changes",
          pageSize: 50,
          search: batch.join("\n"),
          toolName,
        })
        choices.push(...page.choices)
      }
      // A batch of one line lists every match, so keep only the best one per line.
      const best = new Map<string, EntityChoice>()
      for (const choice of choices) {
        const term = choice.value["search_term"]
        const line = typeof term === "string" ? term.toLowerCase() : choice.label.toLowerCase()
        if (!best.has(line)) best.set(line, choice)
      }
      setFound({
        found: best.size,
        lines: lines.length,
        missing: lines.filter((line) => !best.has(line.toLowerCase())),
      })
      onFound([...best.values()])
    } catch (caught) {
      setError(getErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-w-0 gap-1.5">
      <label className="text-sm font-medium" htmlFor={id}>
        Places or Postcodes, One per Line
      </label>
      <Textarea
        className="max-h-48 min-h-20 font-mono text-sm"
        disabled={disabled || busy}
        id={id}
        onChange={(event) => {
          setText(event.currentTarget.value)
        }}
        placeholder="One place on each line"
        value={text}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={disabled || busy || conversationId === null || !text.trim()}
          onClick={() => {
            void find()
          }}
          type="button"
          variant="outline"
        >
          {busy ? "Finding" : "Find and Add"}
        </Button>
        {found ? (
          <p className="text-muted-foreground text-sm tabular-nums" role="status">
            {String(found.lines)} lines · {String(found.found)} found
            {found.missing.length > 0 ? (
              <span className="text-destructive">
                {" "}
                · {String(found.missing.length)} not recognised
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
      {found && found.missing.length > 0 ? (
        <p className="text-muted-foreground text-sm wrap-anywhere">
          Skipped: {found.missing.join(", ")}
        </p>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  )
}
