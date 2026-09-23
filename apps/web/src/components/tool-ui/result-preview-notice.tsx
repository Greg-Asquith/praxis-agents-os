// apps/web/src/components/tool-ui/result-preview-notice.tsx

import { resultListLength, type ResultPreview } from "@/components/tool-ui/result-preview"
import { titleCaseToken } from "@/lib/format"

export function ResultPreviewNotice({
  data,
  index,
  preview,
}: {
  data: unknown
  index?: number
  preview: ResultPreview
}) {
  const counts = preview.lists.filter(
    ({ path }) => index === undefined || path.startsWith(`results.${String(index)}.data.`)
  )
  return (
    <div className="text-muted-foreground grid gap-1 text-xs">
      {counts.map(({ path, total }) => {
        const shown = resultListLength(data, path)
        if (shown === null) return null
        const kind = path.split(".").at(-1) ?? "items"
        return (
          <p key={path}>
            {kind === "rows" ? "" : `${titleCaseToken(kind, "Items")}: `}
            {shown < total ? "Preview: " : ""}
            {shown.toLocaleString()} of {total.toLocaleString()} returned {kind}.
          </p>
        )
      })}
    </div>
  )
}
