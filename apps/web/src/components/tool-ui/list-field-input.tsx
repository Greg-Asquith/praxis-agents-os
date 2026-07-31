// apps/web/src/components/tool-ui/list-field-input.tsx

import { useState, type KeyboardEvent } from "react"
import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

export function ListFieldInput({
  disabled,
  id,
  onChange,
  placeholder,
  value,
}: {
  disabled: boolean
  id: string
  onChange: (value: string[]) => void
  placeholder?: string
  value: string[]
}) {
  const [draft, setDraft] = useState("")

  function addDraft() {
    const item = draft.trim()
    if (!item) {
      return
    }
    onChange([...value, item])
    setDraft("")
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault()
      addDraft()
    } else if (event.key === "Backspace" && !draft && value.length > 0) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div
      className={cn(
        "border-input focus-within:border-ring focus-within:ring-ring/50 flex min-h-8 min-w-0 flex-wrap items-center gap-1.5 rounded-lg border px-2 py-1 focus-within:ring-3",
        disabled && "bg-input/50 pointer-events-none opacity-50"
      )}
    >
      {value.map((item, index) => (
        <span
          className="bg-muted inline-flex max-w-full items-center gap-1 rounded-md py-0.5 pr-0.5 pl-2 text-xs"
          key={`${item}:${String(index)}`}
        >
          <span className="truncate">{item}</span>
          <Button
            aria-label={`Remove ${item}`}
            className="size-5"
            disabled={disabled}
            onClick={() => {
              onChange(value.filter((_entry, entryIndex) => entryIndex !== index))
            }}
            size="icon-xs"
            type="button"
            variant="ghost"
          >
            <XIcon />
          </Button>
        </span>
      ))}
      <Input
        aria-label="Add list item"
        className="h-6 min-w-28 flex-1 border-0 px-0 shadow-none focus-visible:ring-0"
        disabled={disabled}
        id={id}
        onBlur={addDraft}
        onChange={(event) => {
          setDraft(event.currentTarget.value)
        }}
        onKeyDown={handleKeyDown}
        placeholder={value.length === 0 ? (placeholder ?? "Type and press Enter") : "Add another"}
        value={draft}
      />
    </div>
  )
}
