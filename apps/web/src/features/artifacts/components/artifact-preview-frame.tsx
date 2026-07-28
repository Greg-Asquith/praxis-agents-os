// apps/web/src/features/artifacts/components/artifact-preview-frame.tsx

import { MarkdownContent } from "@/components/markdown/markdown-content"
import type { ArtifactContent, ArtifactType } from "@/features/artifacts/types"
import { parseCsv } from "@/lib/csv"

export function ArtifactPreviewFrame({
  artifactType,
  content,
  title,
}: {
  artifactType: ArtifactType
  content: ArtifactContent
  title: string
}) {
  // Artifact content is rendered through typed, sandboxed paths. Never add raw HTML injection here.
  if (artifactType === "html" && content.content !== null) {
    return (
      <iframe
        className="bg-background h-80 w-full rounded-lg border"
        sandbox="allow-scripts"
        srcDoc={content.content}
        title={title}
      />
    )
  }
  if (artifactType === "image-ref" && content.download_url) {
    return (
      <div className="bg-muted/30 flex min-h-64 items-center justify-center rounded-lg border p-3">
        <img
          alt={title}
          className="max-h-128 max-w-full rounded-md object-contain"
          src={content.download_url}
        />
      </div>
    )
  }
  if (artifactType === "markdown" && content.content !== null) {
    return (
      <div className="max-h-128 overflow-auto rounded-lg border p-4">
        <MarkdownContent content={content.content} />
      </div>
    )
  }
  if (artifactType === "csv" && content.content !== null) {
    return <CsvPreview content={content.content} />
  }
  return (
    <pre className="bg-muted/30 max-h-128 overflow-auto rounded-lg border p-4 font-mono text-xs whitespace-pre-wrap">
      {content.content ?? "Preview unavailable"}
    </pre>
  )
}

function CsvPreview({ content }: { content: string }) {
  const rows = withStableIds(parseCsv(content, 101))
  const headings = rows[0]?.values ?? []
  const body = rows.slice(1)
  return (
    <div className="max-h-128 overflow-auto rounded-lg border">
      <table className="w-full min-w-max text-sm">
        <thead className="bg-muted/70 sticky top-0">
          <tr>
            {headings.map((heading) => (
              <th className="border-b px-3 py-2 text-left font-medium" key={heading.id}>
                {heading.value}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row) => (
            <tr className="even:bg-muted/30 border-b last:border-b-0" key={row.id}>
              {row.values.map((cell) => (
                <td className="px-3 py-2 align-top" key={cell.id}>
                  {cell.value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function withStableIds(rows: string[][]) {
  const rowOccurrences = new Map<string, number>()
  return rows.map((row) => {
    const rowKey = row.join("\u0000")
    const rowOccurrence = rowOccurrences.get(rowKey) ?? 0
    rowOccurrences.set(rowKey, rowOccurrence + 1)
    const cellOccurrences = new Map<string, number>()
    return {
      id: `${rowKey}:${String(rowOccurrence)}`,
      values: row.map((value) => {
        const occurrence = cellOccurrences.get(value) ?? 0
        cellOccurrences.set(value, occurrence + 1)
        return { id: `${value}:${String(occurrence)}`, value }
      }),
    }
  })
}
