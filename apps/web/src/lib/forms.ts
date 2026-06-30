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
