// apps/web/src/features/files/components/file-content-view.tsx

import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import { cn } from "@/lib/utils"

type FileContentViewProps = {
  content: string
  name?: string | null
  mediaType?: string | null
  className?: string
}

export function FileContentView({ content, name, mediaType, className }: FileContentViewProps) {
  const kind = contentKind(name ?? null, mediaType ?? null)

  if (kind === "markdown") {
    return (
      <div
        className={cn(
          "bg-muted/30 max-h-80 min-w-0 overflow-auto rounded-md border p-3",
          className
        )}
      >
        <MessageMarkdown className="text-xs leading-relaxed" content={content} />
      </div>
    )
  }

  if (kind === "html") {
    // sandbox="" renders the markup with scripts, forms, and same-origin access disabled.
    return (
      <iframe
        className={cn("h-80 w-full rounded-md border bg-white", className)}
        sandbox=""
        srcDoc={content}
        title={name ?? "HTML preview"}
      />
    )
  }

  return (
    <pre
      className={cn(
        "bg-muted/50 max-h-80 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap",
        className
      )}
    >
      {content}
    </pre>
  )
}

function contentKind(name: string | null, mediaType: string | null): "markdown" | "html" | "plain" {
  const normalizedType = mediaType?.split(";")[0]?.trim().toLowerCase() ?? ""
  if (normalizedType === "text/markdown") {
    return "markdown"
  }
  if (normalizedType === "text/html") {
    return "html"
  }
  const extension = name?.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? ""
  if (extension === "md" || extension === "markdown") {
    return "markdown"
  }
  if (extension === "html" || extension === "htm") {
    return "html"
  }
  return "plain"
}
