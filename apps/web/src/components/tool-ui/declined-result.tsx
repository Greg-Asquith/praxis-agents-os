// apps/web/src/components/tool-ui/declined-result.tsx

import { ApprovalStaticField } from "@/components/tool-ui/approval-static-field"

export function DeclinedResult({
  description,
  reason,
}: {
  description: string
  reason?: string | undefined
}) {
  return (
    <div className="grid min-w-0 gap-3">
      <p className="text-muted-foreground text-sm">{description}</p>
      {reason ? (
        <ApprovalStaticField
          field={{
            key: "denial-message",
            label: "Message to Agent",
            value: reason,
            format: "multiline",
          }}
        />
      ) : null}
    </div>
  )
}
