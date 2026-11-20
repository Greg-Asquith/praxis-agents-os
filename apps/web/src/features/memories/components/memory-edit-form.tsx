// apps/web/src/features/memories/components/memory-edit-form.tsx

import { useId, useState, type ReactNode, type SyntheticEvent } from "react"
import { ChevronDownIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useUpdateMemoryMutation } from "@/features/memories/api/update-memory"
import {
  buildMemoryUpdatePayload,
  memoryFormState,
  type MemoryFormState,
} from "@/features/memories/components/memory-form-model"
import type { Memory } from "@/features/memories/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

export function MemoryEditForm({
  memory,
  onCancel,
  onSaved,
}: {
  memory: Memory
  onCancel: () => void
  onSaved: (memory: Memory) => void
}) {
  const advancedId = useId()
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [state, setState] = useState<MemoryFormState>(() => memoryFormState(memory))
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const mutation = useUpdateMemoryMutation()

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const payload = buildMemoryUpdatePayload(state)
    if (Array.isArray(payload)) {
      setFieldErrors(buildFieldErrors(payload))
      return
    }
    setFieldErrors({})
    try {
      const updated = await mutation.mutateAsync({ memoryId: memory.id, payload })
      onSaved(updated)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn’t Update Memory</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <FieldGroup>
        <FormField error={fieldErrors["memory-title"]} id="memory-title" label="Title">
          <Input
            aria-invalid={Boolean(fieldErrors["memory-title"])}
            id="memory-title"
            maxLength={200}
            value={state.title}
            onChange={(event) => {
              setState((current) => ({ ...current, title: event.target.value }))
            }}
          />
        </FormField>
        <FormField
          error={fieldErrors["memory-content"]}
          helper="Saving keeps the previous wording in History."
          id="memory-content"
          label="Memory"
        >
          <Textarea
            aria-invalid={Boolean(fieldErrors["memory-content"])}
            className="min-h-36"
            id="memory-content"
            value={state.content}
            onChange={(event) => {
              setState((current) => ({ ...current, content: event.target.value }))
            }}
          />
        </FormField>
        <Button
          aria-controls={advancedId}
          aria-expanded={advancedOpen}
          className="text-muted-foreground w-fit"
          onClick={() => {
            setAdvancedOpen((current) => !current)
          }}
          size="sm"
          type="button"
          variant="ghost"
        >
          Advanced
          <ChevronDownIcon
            className={advancedOpen ? "rotate-180 transition-transform" : "transition-transform"}
            data-icon="inline-end"
          />
        </Button>
        <FieldGroup
          className={advancedOpen ? "grid gap-4 sm:grid-cols-2" : "hidden"}
          id={advancedId}
        >
          <FormField
            error={fieldErrors["memory-importance"]}
            id="memory-importance"
            label="Importance"
          >
            <Input
              aria-invalid={Boolean(fieldErrors["memory-importance"])}
              id="memory-importance"
              max={5}
              min={1}
              type="number"
              value={state.importance}
              onChange={(event) => {
                setState((current) => ({ ...current, importance: Number(event.target.value) }))
              }}
            />
          </FormField>
          <FormField
            error={fieldErrors["memory-expiry"]}
            helper="Leave blank to keep the current expiry."
            id="memory-expiry"
            label="Expires In Days"
          >
            <Input
              aria-invalid={Boolean(fieldErrors["memory-expiry"])}
              id="memory-expiry"
              min={1}
              placeholder="No change"
              type="number"
              value={state.expiresInDays}
              onChange={(event) => {
                setState((current) => ({ ...current, expiresInDays: event.target.value }))
              }}
            />
          </FormField>
        </FieldGroup>
      </FieldGroup>
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel} type="button" variant="outline">
          Cancel
        </Button>
        <Button disabled={mutation.isPending} type="submit">
          {mutation.isPending ? "Saving…" : "Save Changes"}
        </Button>
      </div>
    </form>
  )
}

function FormField({
  children,
  error,
  helper,
  id,
  label,
}: {
  children: ReactNode
  error?: string | undefined
  helper?: string | undefined
  id: string
  label: string
}) {
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {children}
      {error ? <FieldError>{error}</FieldError> : null}
      {!error && helper ? <FieldDescription>{helper}</FieldDescription> : null}
    </Field>
  )
}
