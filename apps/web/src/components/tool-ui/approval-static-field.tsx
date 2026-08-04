// apps/web/src/components/tool-ui/approval-static-field.tsx

import type { ApprovalFallbackField } from "@/components/tool-ui/approval-types"
import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolFieldValue } from "@/components/tool-ui/field-value"
import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { cn } from "@/lib/utils"

export function ApprovalStaticField({ field }: { field: ApprovalFallbackField }) {
  if (field.format === "html") {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <p className={fieldLabelClass}>{field.label}</p>
        <HtmlContentFrame
          className="border-input h-60 rounded-lg border"
          html={field.value}
          title={field.label}
        />
      </div>
    )
  }
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className={fieldLabelClass}>{field.label}</p>
      <div
        className={cn(
          fieldWellClass,
          "border-input bg-muted/40 wrap-break-word whitespace-pre-wrap"
        )}
      >
        <ToolFieldValue field={field} />
      </div>
    </div>
  )
}
