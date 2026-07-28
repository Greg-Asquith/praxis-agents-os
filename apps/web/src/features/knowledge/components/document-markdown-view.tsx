// apps/web/src/features/knowledge/components/document-markdown-view.tsx

import { ShieldCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import { MarkdownContent } from "@/components/markdown/markdown-content"
import { DocumentStatusBadge } from "@/features/knowledge/components/document-status-badge"
import { knowledgeContentText } from "@/features/knowledge/content"
import type { KbDocumentDetail } from "@/features/knowledge/types"

export function DocumentMarkdownView({ document }: { document: KbDocumentDetail }) {
  const content = knowledgeContentText(document.content_md)
  if (!content) {
    return (
      <div className="bg-muted/30 flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl p-6 text-center">
        <DocumentStatusBadge status={document.status} />
        <p className="text-muted-foreground max-w-md text-sm">
          {document.processing_error ??
            (document.status === "ready"
              ? "This document has no readable content."
              : "Readable content will appear after processing completes.")}
        </p>
      </div>
    )
  }

  return (
    <article className="min-w-0 overflow-x-auto rounded-xl border p-5 sm:p-7">
      {isUntrustedNode(document.content_md) ? (
        <Badge className="mb-5" variant="outline">
          <ShieldCheckIcon data-icon="inline-start" />
          External Content
        </Badge>
      ) : null}
      <MarkdownContent content={content} />
    </article>
  )
}
