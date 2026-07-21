// apps/web/src/features/integrations/components/connection-label-editor.tsx

import { useState, type KeyboardEvent } from "react"
import { CheckIcon, PencilIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useRenameConnectionMutation } from "@/features/integrations/api/rename-connection"
import { getErrorMessage } from "@/lib/api/errors"

export function ConnectionLabelEditor({
  canEdit,
  connectionId,
  label,
}: {
  canEdit: boolean
  connectionId: string
  label: string
}) {
  const mutation = useRenameConnectionMutation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(label)
  const [error, setError] = useState<string | null>(null)

  function cancel() {
    setDraft(label)
    setEditing(false)
    setError(null)
  }

  async function save() {
    const nextLabel = draft.trim()
    if (!nextLabel) {
      setError("Enter a connection name.")
      return
    }
    try {
      await mutation.mutateAsync({ connectionId, label: nextLabel })
      setEditing(false)
      setError(null)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      cancel()
    }
    if (event.key === "Enter") {
      event.preventDefault()
      void save()
    }
  }

  if (!editing) {
    return (
      <div className="flex min-w-0 items-center gap-1.5">
        <h3 className="truncate text-sm font-medium">{label}</h3>
        {canEdit ? (
          <Button
            aria-label={`Rename ${label}`}
            onClick={() => {
              setEditing(true)
            }}
            size="icon-xs"
            type="button"
            variant="ghost"
          >
            <PencilIcon />
          </Button>
        ) : null}
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex min-w-0 items-center gap-1">
        <Input
          aria-label="Connection name"
          className="h-8 max-w-64"
          disabled={mutation.isPending}
          maxLength={120}
          onChange={(event) => {
            setDraft(event.currentTarget.value)
          }}
          onKeyDown={handleKeyDown}
          value={draft}
        />
        <Button
          aria-label="Save connection name"
          disabled={mutation.isPending}
          onClick={() => void save()}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <CheckIcon />
        </Button>
        <Button
          aria-label="Cancel rename"
          disabled={mutation.isPending}
          onClick={cancel}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <XIcon />
        </Button>
      </div>
      {error ? <p className="text-destructive text-xs">{error}</p> : null}
    </div>
  )
}
