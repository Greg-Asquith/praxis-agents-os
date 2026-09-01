// apps/web/src/integrations/notion/components/write-results.tsx

import { CircleCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { NotionWriteKind, NotionWriteResult } from "@/integrations/notion/lib/write-results"
import { formatDateTime, pluralize } from "@/lib/format"

export function NotionWriteReceipt({
  kind,
  result,
}: {
  kind: NotionWriteKind
  result: NotionWriteResult
}) {
  return (
    <div className="grid gap-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Badge variant="success">
          <CircleCheckIcon />
          Change confirmed
        </Badge>
        {result.pageTruncated ? <Badge variant="warning">Notion response truncated</Badge> : null}
      </div>
      <div className="grid gap-1 text-sm">
        {kind === "create" ? (
          <p>{resultLink(result.title ?? "Created page", result.url)}</p>
        ) : kind === "content" && result.appliedReplacements !== null ? (
          <p>
            Applied {String(result.appliedReplacements)} exact-text{" "}
            {pluralize(result.appliedReplacements, "replacement")}.
          </p>
        ) : (
          <p>Updated the selected page properties.</p>
        )}
        {result.title && kind !== "create" ? (
          <p className="text-muted-foreground">Page: {result.title}</p>
        ) : null}
        {result.lastEditedTime ? (
          <p className="text-muted-foreground text-xs">
            Last edited{" "}
            <time dateTime={result.lastEditedTime}>{formatDateTime(result.lastEditedTime)}</time>
          </p>
        ) : null}
      </div>
    </div>
  )
}

function resultLink(label: string, url: string | null) {
  return url?.startsWith("https://") ? (
    <a
      className="text-link hover:text-primary font-medium underline underline-offset-2"
      href={url}
      rel="noreferrer"
      target="_blank"
    >
      {label}
    </a>
  ) : (
    <span className="font-medium">{label}</span>
  )
}
