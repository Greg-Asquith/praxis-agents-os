// apps/web/src/components/tool-ui/external-content.tsx

import { useState } from "react"
import { ShieldCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { isUntrustedNode, nodeText, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import { titleCaseToken, truncateText } from "@/lib/format"

const CONTENT_PREVIEW_LIMIT = 480

export function ExternalContent({
  label = "External content",
  showSource = true,
  value,
}: {
  label?: string
  showSource?: boolean
  value: string | UntrustedNode
}) {
  const [expanded, setExpanded] = useState(false)
  const content = nodeText(value) ?? ""
  const isLong = content.length > CONTENT_PREVIEW_LIMIT
  const visibleContent = expanded ? content : truncateText(content, CONTENT_PREVIEW_LIMIT, "…")

  return (
    <section
      aria-label={label}
      className="border-border bg-muted/35 min-w-0 rounded-lg border px-3 py-2.5"
      data-slot="external-content"
    >
      <div className="mb-2 flex min-w-0 flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground inline-flex items-center gap-1 text-xs font-medium">
          <ShieldCheckIcon className="size-3.5" />
          External Content
        </span>
        {showSource && isUntrustedNode(value) ? <UntrustedSourceBadge node={value} /> : null}
      </div>
      <p className="text-foreground text-sm leading-relaxed wrap-break-word whitespace-pre-wrap">
        {visibleContent || "No content returned."}
      </p>
      {isLong ? (
        <Button
          className="mt-2 h-auto px-0 py-0"
          onClick={() => {
            setExpanded((current) => !current)
          }}
          size="sm"
          type="button"
          variant="link"
        >
          {expanded ? "Show Less" : "Show Full Content"}
        </Button>
      ) : null}
    </section>
  )
}

function UntrustedSourceBadge({ node }: { node: UntrustedNode }) {
  const sourceKind = titleCaseToken(node.source_kind.replaceAll("_", " "), "External")
  return (
    <Badge
      aria-label={`Source: ${sourceKind}, ${node.source_ref}`}
      className="max-w-full font-mono font-normal"
      title={`${sourceKind}: ${node.source_ref}`}
      variant="outline"
    >
      <span className="truncate">{sourceKind}</span>
      <span aria-hidden="true">·</span>
      <span className="truncate">{node.source_ref}</span>
    </Badge>
  )
}
