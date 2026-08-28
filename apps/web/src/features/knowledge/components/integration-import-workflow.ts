// apps/web/src/features/knowledge/components/integration-import-workflows.ts

import type { KbIntegrationSourcePreview } from "@/features/knowledge/types"

import { INTEGRATION_IMPORT_IS_PRIVATE_DEFAULT } from "./integration-import-form-model"

export type IntegrationImportPreviewSelection = {
  preview: KbIntegrationSourcePreview
  resourceId: string
}

export type IntegrationImportWorkflowState = {
  isPrivate: boolean
  previewSelection: IntegrationImportPreviewSelection | null
  title: string
}

export type IntegrationImportWorkflowAction =
  | { type: "choose-source" }
  | { type: "rename"; title: string }
  | { type: "review"; selection: IntegrationImportPreviewSelection }
  | { type: "set-private"; isPrivate: boolean }

export function createIntegrationImportWorkflowState(): IntegrationImportWorkflowState {
  return {
    isPrivate: INTEGRATION_IMPORT_IS_PRIVATE_DEFAULT,
    previewSelection: null,
    title: "",
  }
}

export function integrationImportWorkflowReducer(
  state: IntegrationImportWorkflowState,
  action: IntegrationImportWorkflowAction
): IntegrationImportWorkflowState {
  switch (action.type) {
    case "choose-source":
      return { ...state, previewSelection: null, title: "" }
    case "rename":
      return { ...state, title: action.title }
    case "review":
      return {
        ...state,
        previewSelection: action.selection,
        title: action.selection.preview.title,
      }
    case "set-private":
      return { ...state, isPrivate: action.isPrivate }
  }
}
