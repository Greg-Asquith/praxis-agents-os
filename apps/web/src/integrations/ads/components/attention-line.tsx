// apps/web/src/integrations/ads/components/attention-line.tsx

import { TriangleAlertIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Says how many changes block approval, with a button that shows them. */
export function AttentionLine({ count, onShow }: { count: number; onShow: () => void }) {
  if (count === 0) return null
  return (
    <div
      className="border-destructive/30 bg-destructive/5 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
      role="alert"
    >
      <p className="text-destructive flex items-center gap-2 text-sm">
        <TriangleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
        {count === 1
          ? "1 change needs attention before you can approve."
          : `${String(count)} changes need attention before you can approve.`}
      </p>
      <Button onClick={onShow} size="sm" type="button" variant="outline">
        Show Them
      </Button>
    </div>
  )
}
