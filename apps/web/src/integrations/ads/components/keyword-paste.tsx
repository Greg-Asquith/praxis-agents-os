// apps/web/src/integrations/ads/components/keyword-paste.tsx

import { useId, useState } from "react"

import { Textarea } from "@/components/ui/textarea"
import {
  formatKeywordLine,
  matchTypeCounts,
  parseKeywordLines,
  type PastedKeyword,
} from "@/integrations/ads/lib/keyword-notation"

function asText(keywords: readonly PastedKeyword[]): string {
  return keywords.map(formatKeywordLine).join("\n")
}

/** Takes keywords pasted one per line in Google's notation, and counts them by match type. */
export function KeywordPaste({
  disabled,
  keywords,
  label,
  onChange,
}: {
  disabled: boolean
  keywords: readonly PastedKeyword[]
  label: string
  onChange: (keywords: PastedKeyword[]) => void
}) {
  const id = useId()
  // What was typed, kept while it means the same as `keywords`, so blank lines and spaces stay
  // as the operator left them. A change from elsewhere, such as a match type, replaces it.
  const [draft, setDraft] = useState<string | null>(null)
  const canonical = asText(keywords)
  const shown = draft !== null && asText(parseKeywordLines(draft)) === canonical ? draft : canonical
  const counts = matchTypeCounts(keywords)
  return (
    <div className="grid min-w-0 gap-1.5">
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <Textarea
        className="max-h-64 min-h-24 font-mono text-sm"
        disabled={disabled}
        id={id}
        onChange={(event) => {
          setDraft(event.currentTarget.value)
          onChange(parseKeywordLines(event.currentTarget.value))
        }}
        placeholder={'[exact match]\n"phrase match"\nbroad match'}
        value={shown}
      />
      <p className="text-muted-foreground text-xs tabular-nums">
        {String(keywords.length)} total · {String(counts.phrase)} phrase · {String(counts.exact)}{" "}
        exact · {String(counts.broad)} broad
      </p>
    </div>
  )
}
