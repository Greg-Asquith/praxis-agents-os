// apps/web/src/features/knowledge/components/privacy-field.tsx

import { useId } from "react"

import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"

export function PrivacyField({
  checked,
  onCheckedChange,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
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
        <p className="text-muted-foreground text-xs">Only visible to you.</p>
      </div>
    </div>
  )
}
