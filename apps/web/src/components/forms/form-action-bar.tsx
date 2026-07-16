// apps/web/src/components/forms/form-action-bar.tsx

import { Link } from "@tanstack/react-router"
import { CheckIcon, SaveIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

type FormCancelRoute = "/agents" | "/schedules" | "/skills"

export function FormActionBar({
  cancelLabel,
  cancelTo,
  disableSubmit,
  form,
  isSubmitting,
  pendingLabel,
  stateMessage,
  submitLabel,
}: {
  cancelLabel: string
  cancelTo: FormCancelRoute
  disableSubmit: boolean
  form?: string
  isSubmitting: boolean
  pendingLabel: string
  stateMessage: string
  submitLabel: string
}) {
  return (
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
          <Button className="w-full sm:w-auto" disabled={disableSubmit} form={form} type="submit">
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
  )
}
