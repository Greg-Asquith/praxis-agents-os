// apps/web/src/components/tool-ui/provider-content-preview.tsx

import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import type { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"

export function ProviderContentPreview<Meta extends { subject?: string }>({
  query,
  fallback,
  errorFallback,
  renderMeta,
}: {
  query: ReturnType<typeof providerPreviewQueryOptions<Meta>>
  fallback: ReactNode
  errorFallback?: ReactNode
  renderMeta?: (meta: Meta) => ReactNode
}) {
  const preview = useQuery(query)
  if (query.enabled === false) return <>{errorFallback ?? fallback}</>
  if (preview.isPending) return <>{fallback}</>
  if (preview.isError) return <>{errorFallback ?? fallback}</>

  return (
    <div className="grid min-w-0 gap-2">
      {renderMeta?.(preview.data.meta)}
      {preview.data.content_type === "html" ? (
        <HtmlContentFrame
          className="h-120"
          html={preview.data.content}
          title={preview.data.meta.subject?.trim() ? preview.data.meta.subject : "Email message"}
        />
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-wrap">
          {preview.data.content || "No message content."}
        </p>
      )}
    </div>
  )
}
