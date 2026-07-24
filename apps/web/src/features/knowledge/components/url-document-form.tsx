// apps/web/src/features/knowledge/components/url-document-form.tsx

import { useState, type SyntheticEvent } from "react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCreateDocumentFromUrlMutation } from "@/features/knowledge/api/create-document-from-url"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import {
  buildUrlDocumentPayload,
  type UrlDocumentFormState,
} from "@/features/knowledge/components/url-document-form-model"
import { getErrorMessage } from "@/lib/api/errors"
import { formString, type FormValidationEntry } from "@/lib/forms"

export function UrlDocumentForm({ onSaved }: { onSaved: () => void }) {
  const mutation = useCreateDocumentFromUrlMutation()
  const [isPrivate, setIsPrivate] = useState(false)
  const [validationEntries, setValidationEntries] = useState<FormValidationEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const formData = new FormData(event.currentTarget)
    const state: UrlDocumentFormState = {
      title: formString(formData, "title"),
      url: formString(formData, "url"),
      isPrivate,
    }
    const payload = buildUrlDocumentPayload(state)
    if (Array.isArray(payload)) {
      setValidationEntries(payload)
      return
    }
    setValidationEntries([])
    try {
      await mutation.mutateAsync(payload)
      onSaved()
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
      <FormAlerts
        error={error}
        errorTitle="Couldn’t add URL"
        validationEntries={validationEntries}
      />
      <div className="grid gap-2">
        <Label htmlFor="knowledge-url-title">Title</Label>
        <Input autoComplete="off" id="knowledge-url-title" maxLength={500} name="title" />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="knowledge-url">URL</Label>
        <Input
          id="knowledge-url"
          name="url"
          placeholder="https://example.com/handbook…"
          type="url"
          autoComplete="url"
        />
      </div>
      <PrivacyField checked={isPrivate} onCheckedChange={setIsPrivate} />
      <DialogFooter>
        <DialogClose render={<Button disabled={mutation.isPending} variant="outline" />}>
          Cancel
        </DialogClose>
        <Button disabled={mutation.isPending} type="submit">
          {mutation.isPending ? "Queuing…" : "Add URL"}
        </Button>
      </DialogFooter>
    </form>
  )
}
