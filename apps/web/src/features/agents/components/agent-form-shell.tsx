// apps/web/src/features/agents/components/agent-form-shell.tsx

import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { CheckIcon, SaveIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { AgentFormValidationEntry } from "@/features/agents/components/agent-form-model"

export function AgentFormShell({
  cancelLabel,
  cancelTo,
  children,
  formError,
  isDirty,
  isSubmitting,
  mode,
  pendingLabel,
  submitLabel,
  validationEntries,
}: {
  cancelLabel: string
  cancelTo: "/agents"
  children: ReactNode
  formError: string | null
  isDirty: boolean
  isSubmitting: boolean
  mode: "create" | "edit"
  pendingLabel: string
  submitLabel: string
  validationEntries: AgentFormValidationEntry[]
}) {
  const disableSubmit = isSubmitting || (mode === "edit" && !isDirty)
  const stateMessage =
    mode === "edit"
      ? isDirty
        ? "Unsaved changes"
        : "No unsaved changes"
      : "Ready to create when required fields are complete"

  return (
    <div className="flex flex-col gap-4">
      {formError ? (
        <Alert variant="destructive">
          <AlertTitle>Agent not saved</AlertTitle>
          <AlertDescription>{formError}</AlertDescription>
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

      <div className="flex flex-col gap-4">{children}</div>

      <div className="bg-background/95 sticky -bottom-6 z-10 -mx-4 border-t px-4 py-3 shadow-[0_-12px_32px_rgba(15,23,42,0.08)] backdrop-blur md:-mx-6 md:px-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted-foreground text-sm">{stateMessage}</p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              className="w-full sm:w-auto"
              disabled={isSubmitting}
              render={<Link to={cancelTo} />}
              type="button"
              variant="outline"
            >
              {cancelLabel}
            </Button>
            <Button className="w-full sm:w-auto" disabled={disableSubmit} type="submit">
              {isSubmitting ? (
                <>
                  <SaveIcon data-icon="inline-start" />
                  {pendingLabel}
                </>
              ) : (
                <>
                  <CheckIcon data-icon="inline-start" />
                  {submitLabel}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
