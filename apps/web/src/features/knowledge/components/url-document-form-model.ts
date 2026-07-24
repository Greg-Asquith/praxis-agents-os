// apps/web/src/features/knowledge/components/url-document-form-model.ts

import type { KbUrlDocumentCreateRequest } from "@/features/knowledge/types"
import type { FormValidationEntry } from "@/lib/forms"

export type UrlDocumentFormState = {
  isPrivate: boolean
  title: string
  url: string
}

export function validateUrlDocumentForm(state: UrlDocumentFormState): FormValidationEntry[] {
  const entries: FormValidationEntry[] = []
  const title = state.title.trim()
  const url = state.url.trim()
  if (!title) {
    entries.push({ fieldId: "knowledge-url-title", label: "Title", message: "Title is required." })
  } else if (title.length > 500) {
    entries.push({
      fieldId: "knowledge-url-title",
      label: "Title",
      message: "Title must be 500 characters or fewer.",
    })
  }
  if (!url) {
    entries.push({ fieldId: "knowledge-url", label: "URL", message: "URL is required." })
  } else {
    try {
      const parsed = new URL(url)
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        throw new Error("unsupported protocol")
      }
    } catch {
      entries.push({
        fieldId: "knowledge-url",
        label: "URL",
        message: "Enter a valid HTTP or HTTPS URL.",
      })
    }
  }
  return entries
}

export function buildUrlDocumentPayload(
  state: UrlDocumentFormState
): KbUrlDocumentCreateRequest | FormValidationEntry[] {
  const validation = validateUrlDocumentForm(state)
  if (validation.length > 0) {
    return validation
  }
  return {
    title: state.title.trim(),
    url: state.url.trim(),
    is_private: state.isPrivate,
  }
}
