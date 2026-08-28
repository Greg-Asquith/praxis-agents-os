// apps/web/src/features/knowledge/components/privacy-field.tsx

import { useId } from "react"

import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"

export function PrivacyField({
  checked,
  onCheckedChange,
  sharedDescription,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  sharedDescription?: string
}) {
  const inputId = useId()

  return (
    <div className="flex items-start gap-3 rounded-lg border p-3">
      <Checkbox
        aria-label="Private, only visible to you"
        checked={checked}
        id={inputId}
        onCheckedChange={onCheckedChange}
      />
      <div className="grid gap-0.5">
        <Label htmlFor={inputId}>Private</Label>
        <p className="text-muted-foreground text-xs">
          {checked ? "Only visible to you." : (sharedDescription ?? "Visible to the workspace.")}
        </p>
      </div>
    </div>
  )
}
