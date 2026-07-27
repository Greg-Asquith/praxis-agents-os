// apps/web/src/features/memories/components/memory-form-model.ts

import type { Memory, MemoryKind, MemoryUpdateRequest } from "@/features/memories/types"
import type { FormValidationEntry } from "@/lib/forms"

export const MEMORY_CONTENT_LIMITS = {
  core: 500,
  note: 2_000,
} as const satisfies Record<MemoryKind, number>

export type MemoryFormState = {
  title: string
  content: string
  importance: number
  expiresInDays: string
}

export function memoryFormState(memory: Memory): MemoryFormState {
  return {
    title: memory.title,
    content: memory.content_md,
    importance: memory.importance,
    expiresInDays: "",
  }
}

export function validateMemoryForm(state: MemoryFormState, memory: Memory): FormValidationEntry[] {
  const entries: FormValidationEntry[] = []
  const title = state.title.trim()
  const content = state.content.trim()
  if (!title) {
    entries.push({ fieldId: "memory-title", label: "Title", message: "Title is required." })
  } else if (title.length > 200) {
    entries.push({
      fieldId: "memory-title",
      label: "Title",
      message: "Title must be 200 characters or fewer.",
    })
  }
  const contentLimit = MEMORY_CONTENT_LIMITS[memory.kind]
  if (!content) {
    entries.push({
      fieldId: "memory-content",
      label: "Memory",
      message: "Memory content is required.",
    })
  } else if (content.length > contentLimit) {
    entries.push({
      fieldId: "memory-content",
      label: "Memory",
      message: `Memory content must be ${contentLimit.toLocaleString()} characters or fewer.`,
    })
  }
  if (!Number.isInteger(state.importance) || state.importance < 1 || state.importance > 5) {
    entries.push({
      fieldId: "memory-importance",
      label: "Importance",
      message: "Importance must be between 1 and 5.",
    })
  }
  if (state.expiresInDays) {
    const expiry = Number(state.expiresInDays)
    if (!Number.isInteger(expiry) || expiry <= 0) {
      entries.push({
        fieldId: "memory-expiry",
        label: "Expiry",
        message: "Expiry must be a whole number of days greater than zero.",
      })
    }
  }
  return entries
}

export function buildMemoryUpdatePayload(
  state: MemoryFormState,
  memory: Memory
): MemoryUpdateRequest | FormValidationEntry[] {
  const validation = validateMemoryForm(state, memory)
  if (validation.length > 0) {
    return validation
  }
  const payload: MemoryUpdateRequest = {
    title: state.title.trim(),
    content_md: state.content.trim(),
    importance: state.importance,
  }
  if (state.expiresInDays) {
    payload.expires_in_days = Number(state.expiresInDays)
  }
  return payload
}
