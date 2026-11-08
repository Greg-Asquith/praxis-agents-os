// apps/web/src/components/tool-ui/chart-export-buttons.tsx

import { DownloadIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

export function ChartExportButtons({
  exporting,
  onExport,
  size,
}: {
  exporting: boolean
  onExport: (format: "png" | "svg") => void
  size: "sm" | "xs"
}) {
  return (
    <div className="flex gap-1">
      {(["png", "svg"] as const).map((format) => (
        <Button
          aria-label={`Download ${format.toUpperCase()}`}
          disabled={exporting}
          key={format}
          onClick={() => {
            onExport(format)
          }}
          size={size}
          type="button"
          variant="outline"
        >
          <DownloadIcon data-icon="inline-start" />
          {format.toUpperCase()}
        </Button>
      ))}
    </div>
  )
}
