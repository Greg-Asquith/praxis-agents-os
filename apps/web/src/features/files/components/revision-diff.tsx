// apps/web/src/features/files/components/revision-diff.ts

import { diffTooLarge, lineDiff, type LineDiffItem } from "@/features/files/diff"

export function RevisionDiff({
  leftContent,
  leftLabel,
  rightContent,
  rightLabel,
}: {
  leftContent: string
  leftLabel: string
  rightContent: string
  rightLabel: string
}) {
  if (diffTooLarge(leftContent, rightContent)) {
    return (
      <div className="bg-muted/40 rounded-md border p-3 text-sm">
        This diff is too large to render inline. Open each revision content view to inspect it.
      </div>
    )
  }

  const items = lineDiff(leftContent, rightContent)

  return (
    <div className="min-w-0 overflow-hidden rounded-md border">
      <div className="bg-muted/40 grid grid-cols-2 gap-2 border-b px-3 py-2 text-xs">
        <span className="truncate">Base: {leftLabel}</span>
        <span className="truncate">Compare: {rightLabel}</span>
      </div>
      <pre className="max-h-96 overflow-auto p-0 text-xs leading-5">
        {items.map((item, index) => (
          <DiffLine item={item} key={`${item.kind}-${String(index)}`} />
        ))}
      </pre>
    </div>
  )
}

function DiffLine({ item }: { item: LineDiffItem }) {
  const marker = item.kind === "added" ? "+" : item.kind === "removed" ? "-" : " "
  const className =
    item.kind === "added"
      ? "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
      : item.kind === "removed"
        ? "bg-red-500/10 text-red-800 dark:text-red-300"
        : "text-muted-foreground"

  return (
    <div className={className}>
      <span className="inline-block w-6 px-2 select-none">{marker}</span>
      <span>{item.text || " "}</span>
    </div>
  )
}
