// apps/web/src/lib/forms.ts

export function formString(formData: FormData, name: string) {
  const value = formData.get(name)
  return typeof value === "string" ? value : ""
}

export function formNumber(formData: FormData, name: string, fallback: number) {
  const value = formString(formData, name)
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export type FormValidationEntry = {
  fieldId: string
  label: string
  message: string
}

export function buildFieldErrors(entries: readonly FormValidationEntry[]) {
  return entries.reduce<Record<string, string>>((errors, entry) => {
    errors[entry.fieldId] = entry.message
    return errors
  }, {})
}
