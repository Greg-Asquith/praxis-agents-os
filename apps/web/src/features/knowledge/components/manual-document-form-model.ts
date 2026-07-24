// apps/web/src/features/knowledge/components/manual-document-form-model.ts

import type { KbManualDocumentCreateRequest } from "@/features/knowledge/types"
import type { FormValidationEntry } from "@/lib/forms"

export type ManualDocumentFormState = {
  content: string
  isPrivate: boolean
  title: string
}

export function validateManualDocumentForm(state: ManualDocumentFormState): FormValidationEntry[] {
  const entries: FormValidationEntry[] = []
  if (!state.title.trim()) {
    entries.push({ fieldId: "knowledge-title", label: "Title", message: "Title is required." })
  } else if (state.title.trim().length > 500) {
    entries.push({
      fieldId: "knowledge-title",
      label: "Title",
      message: "Title must be 500 characters or fewer.",
    })
  }
  if (!state.content.trim()) {
    entries.push({
      fieldId: "knowledge-content",
      label: "Content",
      message: "Content is required.",
    })
  }
  return entries
}

export function buildManualDocumentPayload(
  state: ManualDocumentFormState
): KbManualDocumentCreateRequest | FormValidationEntry[] {
  const validation = validateManualDocumentForm(state)
  if (validation.length > 0) {
    return validation
  }
  return {
    title: state.title.trim(),
    content_md: state.content.trim(),
    is_private: state.isPrivate,
  }
}
