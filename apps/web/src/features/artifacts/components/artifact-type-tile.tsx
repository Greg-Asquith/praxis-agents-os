// apps/web/src/features/artifacts/components/artifact-type-tile.tsx

import { FileCode2Icon, FileTextIcon, ImageIcon, TableIcon, WorkflowIcon } from "lucide-react"

import type { ArtifactType } from "@/features/artifacts/types"
import { cn } from "@/lib/utils"

const TYPE_ICONS = {
  csv: TableIcon,
  html: FileCode2Icon,
  "image-ref": ImageIcon,
  markdown: FileTextIcon,
  mermaid: WorkflowIcon,
} satisfies Record<ArtifactType, typeof FileCode2Icon>

export function ArtifactTypeTile({
  size = "md",
  type,
}: {
  size?: "sm" | "md"
  type: ArtifactType
}) {
  const Icon = TYPE_ICONS[type]
  return (
    <span
      aria-hidden="true"
      className={cn(
        "bg-accent text-primary flex shrink-0 items-center justify-center rounded-md border",
        size === "sm" ? "size-9" : "size-10"
      )}
      data-artifact-type={type}
    >
      <Icon className="size-5" />
    </span>
  )
}
