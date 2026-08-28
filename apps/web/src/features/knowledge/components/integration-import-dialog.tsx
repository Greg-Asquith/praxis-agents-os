// apps/web/src/features/knowledge/components/integration-import-dialog.tsx

import { useReducer, useState, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ProviderMark } from "@/features/integrations/components/provider-mark"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { useCreateDocumentFromIntegrationMutation } from "@/features/knowledge/api/create-document-from-integration"
import {
  buildIntegrationImportPayload,
  integrationImportErrorMessage,
} from "@/features/knowledge/components/integration-import-form-model"
import { IntegrationImportReview } from "@/features/knowledge/components/integration-import-review"
import { IntegrationImportSourcePicker } from "@/features/knowledge/components/integration-import-source-picker"
import {
  createIntegrationImportWorkflowState,
  integrationImportWorkflowReducer,
} from "@/features/knowledge/components/integration-import-workflow"
import { getErrorMessage } from "@/lib/api/errors"
import type { FormValidationEntry } from "@/lib/forms"

export function IntegrationImportDialog({
  connections,
  onOpenChange,
  open,
  provider,
}: {
  connections: IntegrationConnection[]
  onOpenChange: (open: boolean) => void
  open: boolean
  provider: IntegrationProvider
}) {
  const [workflow, dispatch] = useReducer(
    integrationImportWorkflowReducer,
    undefined,
    createIntegrationImportWorkflowState
  )
  const [sourcePending, setSourcePending] = useState(false)
  const [validationEntries, setValidationEntries] = useState<FormValidationEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateDocumentFromIntegrationMutation()
  const isPending = sourcePending || createMutation.isPending
  const errorTitle = `Couldn’t import from ${provider.display_name}`

  function chooseSource() {
    setValidationEntries([])
    setError(null)
    dispatch({ type: "choose-source" })
  }

  async function importPage(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!workflow.previewSelection) {
      return
    }
    const payload = buildIntegrationImportPayload({
      integrationResourceId: workflow.previewSelection.resourceId,
      isPrivate: workflow.isPrivate,
      source: workflow.previewSelection.preview.reference,
      title: workflow.title,
    })
    if (Array.isArray(payload)) {
      setValidationEntries(payload)
      return
    }
    setError(null)
    setValidationEntries([])
    try {
      await createMutation.mutateAsync(payload)
      onOpenChange(false)
    } catch (mutationError) {
      setError(integrationImportErrorMessage(getErrorMessage(mutationError)))
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!isPending) {
          onOpenChange(nextOpen)
        }
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] min-w-0 overflow-x-hidden overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ProviderMark providerKey={provider.provider_key} />
            Import from {provider.display_name}
          </DialogTitle>
          <DialogDescription>
            Choose one source to add to the Knowledge Base.
          </DialogDescription>
        </DialogHeader>

        {workflow.previewSelection ? (
          <IntegrationImportReview
            error={error}
            errorTitle={errorTitle}
            isPending={createMutation.isPending}
            isPrivate={workflow.isPrivate}
            onBack={chooseSource}
            onIsPrivateChange={(isPrivate) => {
              dispatch({ isPrivate, type: "set-private" })
            }}
            onSubmit={(event) => void importPage(event)}
            onTitleChange={(title) => {
              dispatch({ title, type: "rename" })
            }}
            preview={workflow.previewSelection.preview}
            title={workflow.title}
            validationEntries={validationEntries}
          />
        ) : (
          <>
            <IntegrationImportSourcePicker
              connections={connections}
              errorTitle={errorTitle}
              isPrivate={workflow.isPrivate}
              onPendingChange={setSourcePending}
              onPreviewLoaded={(selection) => {
                dispatch({ selection, type: "review" })
              }}
              open={open}
              provider={provider}
            />
            <DialogFooter className="mx-0 mb-0 min-w-0 rounded-lg">
              <DialogClose render={<Button disabled={isPending} variant="outline" />}>
                Cancel
              </DialogClose>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
