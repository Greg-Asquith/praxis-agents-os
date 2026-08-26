// apps/web/src/components/ui/copy-text-button.tsx

import { CheckIcon, CopyIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"

export function CopyTextButton({
  label,
  text = false,
  value,
}: {
  label: string
  text?: boolean
  value: string
}) {
  const { copied, copy } = useClipboardCopy()
  return (
    <Button
      aria-label={`${copied ? "Copied" : "Copy"} ${label}`}
      onClick={() => {
        void copy(value)
      }}
      size={text ? "xs" : "icon-xs"}
      type="button"
      variant="ghost"
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      {text ? (copied ? "Copied" : "Copy names") : null}
    </Button>
  )
}
