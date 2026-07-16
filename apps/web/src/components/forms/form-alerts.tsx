// apps/web/src/components/forms/form-alerts.tsx

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import type { FormValidationEntry } from "@/lib/forms"

export function FormAlerts({
  error,
  errorTitle,
  validationEntries,
}: {
  error: string | null
  errorTitle: string
  validationEntries: readonly FormValidationEntry[]
}) {
  return (
    <>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>{errorTitle}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {validationEntries.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>Review required fields</AlertTitle>
          <AlertDescription>
            <ul className="flex list-disc flex-col gap-1 pl-4">
              {validationEntries.map((entry) => (
                <li key={entry.fieldId}>
                  <a href={`#${entry.fieldId}`}>{entry.label}</a>: {entry.message}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}
