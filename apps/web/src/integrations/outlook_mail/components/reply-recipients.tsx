// apps/web/src/integrations/outlook_mail/components/reply-recipients.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import type { OutlookDraftArgs } from "@/integrations/outlook_mail/lib/write-args"

export function OutlookReplyRecipients({
  args,
  disabled,
  onFieldEdit,
}: {
  args: OutlookDraftArgs | null
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  if (!args?.replyTo) return null
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p>
        To uses the reply recipients from Outlook. Replacing Cc or Bcc replaces the list for that
        field.
      </p>
      {(["cc", "bcc"] as const).map((key) => {
        const label = key === "cc" ? "Cc" : "Bcc"
        const values = args[key]
        return (
          <div className="flex flex-wrap items-center gap-2" key={key}>
            <span>
              {label}:{" "}
              {values === null
                ? "Keep reply recipients from Outlook"
                : values.length === 0
                  ? "No recipients"
                  : values.join(", ")}
            </span>
            {values === null && !disabled ? (
              <Button
                onClick={() => {
                  onFieldEdit(key, [])
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                Clear {label}
              </Button>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
