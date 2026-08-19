// apps/web/src/features/classifiers/components/classifiers-settings-panel.tsx

import { useState } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"
import { PlusIcon, Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useCreateClassifierMutation } from "@/features/classifiers/api/create-classifier"
import { useDeleteClassifierMutation } from "@/features/classifiers/api/delete-classifier"
import { classifiersQueryOptions } from "@/features/classifiers/api/list-classifiers"
import { useUpdateClassifierMutation } from "@/features/classifiers/api/update-classifier"
import { ClassifierDialog } from "@/features/classifiers/components/classifier-dialog"
import { ClassifiersTable } from "@/features/classifiers/components/classifiers-table"
import type { Classifier, ClassifierCreateRequest } from "@/features/classifiers/types"
import { modelCatalogQueryOptions } from "@/features/models/api/list-model-catalog"
import { getErrorMessage } from "@/lib/api/errors"

type ClassifierEditor = { classifier: Classifier | null; key: string }

export function ClassifiersSettingsPanel() {
  const [{ data }, { data: modelCatalog }] = useSuspenseQueries({
    queries: [
      classifiersQueryOptions({ includeInactive: true, limit: 100 }),
      modelCatalogQueryOptions(),
    ],
  })
  const createMutation = useCreateClassifierMutation()
  const updateMutation = useUpdateClassifierMutation()
  const deleteMutation = useDeleteClassifierMutation()
  const [editor, setEditor] = useState<ClassifierEditor | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Classifier | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const isSaving = createMutation.isPending || updateMutation.isPending

  async function saveClassifier(payload: ClassifierCreateRequest) {
    if (editor?.classifier) {
      return updateMutation.mutateAsync({
        classifierId: editor.classifier.id,
        payload,
      })
    }
    return createMutation.mutateAsync(payload)
  }

  async function deleteClassifier() {
    if (!deleteTarget) return
    setDeleteError(null)
    try {
      await deleteMutation.mutateAsync(deleteTarget.id)
      setDeleteTarget(null)
    } catch (error) {
      setDeleteError(getErrorMessage(error))
    }
  }

  function openCreateDialog() {
    setEditor({ classifier: null, key: "create" })
  }

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader className="px-1">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Classifiers</CardTitle>
            <CardDescription className="mt-1 max-w-2xl">
              Give agents reusable categories and judging guidance for routing, tagging, and review.
              Changes apply when the next agent run starts.
            </CardDescription>
          </div>
          {data.classifiers.length > 0 ? (
            <Button onClick={openCreateDialog} type="button">
              <PlusIcon data-icon="inline-start" />
              New Classifier
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-1">
        {deleteError ? (
          <Alert variant="destructive">
            <AlertTitle>Classifier not deleted</AlertTitle>
            <AlertDescription>{deleteError}</AlertDescription>
          </Alert>
        ) : null}
        <ClassifiersTable
          classifiers={data.classifiers}
          modelCatalog={modelCatalog}
          onCreate={openCreateDialog}
          onDelete={(classifier) => {
            setDeleteError(null)
            setDeleteTarget(classifier)
          }}
          onEdit={(classifier) => {
            setEditor({ classifier, key: classifier.id })
          }}
        />
      </CardContent>

      {editor ? (
        <ClassifierDialog
          classifier={editor.classifier}
          isPending={isSaving}
          key={editor.key}
          modelCatalog={modelCatalog}
          onOpenChange={(open) => {
            if (!open && !isSaving) setEditor(null)
          }}
          onSubmit={saveClassifier}
          open
        />
      ) : null}

      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete Classifier"
        confirmPendingLabel="Deleting"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.display_name}? Agents keep the saved tool selection, but it stays unavailable unless you recreate this tool name.`
            : "Delete this classifier?"
        }
        isPending={deleteMutation.isPending}
        onConfirm={deleteClassifier}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        open={deleteTarget !== null}
        title="Delete classifier?"
      />
    </Card>
  )
}
