// apps/web/src/features/knowledge/components/manual-document-form.tsx

import { useState, type SyntheticEvent } from "react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useCreateDocumentMutation } from "@/features/knowledge/api/create-document"
import { useUpdateDocumentMutation } from "@/features/knowledge/api/update-document"
import {
  buildManualDocumentPayload,
  type ManualDocumentFormState,
} from "@/features/knowledge/components/manual-document-form-model"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import { knowledgeContentText } from "@/features/knowledge/content"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formString, type FormValidationEntry } from "@/lib/forms"

export function ManualDocumentForm({
  document = null,
  onSaved,
}: {
  document?: KbDocumentDetail | null
  onSaved: () => void
}) {
  const createMutation = useCreateDocumentMutation()
  const updateMutation = useUpdateDocumentMutation()
  const [isPrivate, setIsPrivate] = useState(document?.is_private ?? false)
  const [validationEntries, setValidationEntries] = useState<FormValidationEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const isPending = createMutation.isPending || updateMutation.isPending

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const formData = new FormData(event.currentTarget)
    const state: ManualDocumentFormState = {
      title: formString(formData, "title"),
      content: formString(formData, "content"),
      isPrivate,
    }
    const payload = buildManualDocumentPayload(state)
    if (Array.isArray(payload)) {
      setValidationEntries(payload)
      return
    }
    setValidationEntries([])
    try {
      if (document) {
        await updateMutation.mutateAsync({
          documentId: document.id,
          payload: { title: payload.title, content_md: payload.content_md },
        })
      } else {
        await createMutation.mutateAsync(payload)
      }
      onSaved()
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
      <FormAlerts
        error={error}
        errorTitle={document ? "Couldn’t update document" : "Couldn’t add document"}
        validationEntries={validationEntries}
      />
      <div className="grid gap-2">
        <Label htmlFor="knowledge-title">Title</Label>
        <Input
          autoComplete="off"
          defaultValue={document?.title ?? ""}
          id="knowledge-title"
          maxLength={500}
          name="title"
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="knowledge-content">Markdown content</Label>
        <Textarea
          autoComplete="off"
          className="min-h-56 font-mono text-sm"
          defaultValue={knowledgeContentText(document?.content_md ?? null) ?? ""}
          id="knowledge-content"
          name="content"
        />
      </div>
      {!document ? <PrivacyField checked={isPrivate} onCheckedChange={setIsPrivate} /> : null}
      <DialogFooter>
        <DialogClose render={<Button disabled={isPending} variant="outline" />}>Cancel</DialogClose>
        <Button disabled={isPending} type="submit">
          {isPending ? "Saving…" : document ? "Save Changes" : "Add Document"}
        </Button>
      </DialogFooter>
    </form>
  )
}
