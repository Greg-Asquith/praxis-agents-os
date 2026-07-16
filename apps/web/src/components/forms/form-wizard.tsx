// apps/web/src/components/forms/form-wizard.tsx

import { useCallback, useImperativeHandle, useState, type ReactNode, type Ref } from "react"
import { Link } from "@tanstack/react-router"
import { ArrowLeftIcon, ArrowRightIcon, CheckIcon, SaveIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type FormWizardCancelRoute = "/agents" | "/schedules" | "/skills"

export type FormWizardStep<StepId extends string> = {
  description?: string
  id: StepId
  optional?: boolean
  title: string
}

export type FormWizardNavigation<StepId extends string> = {
  goToStep: (stepId: StepId) => void
}

export function FormWizard<StepId extends string>({
  cancelLabel,
  cancelTo,
  children,
  disableSubmit = false,
  form,
  isSubmitting,
  navigationRef,
  pendingLabel,
  steps,
  submitLabel,
  validateStep,
}: {
  cancelLabel: string
  cancelTo: FormWizardCancelRoute
  children: (activeStepId: StepId) => ReactNode
  disableSubmit?: boolean
  form?: string
  isSubmitting: boolean
  navigationRef?: Ref<FormWizardNavigation<StepId>>
  pendingLabel: string
  steps: readonly [FormWizardStep<StepId>, ...FormWizardStep<StepId>[]]
  submitLabel: string
  validateStep: (stepId: StepId) => boolean
}) {
  const [activeIndex, setActiveIndex] = useState(0)
  const activeStep = steps[activeIndex] ?? steps[0]
  const isFinalStep = activeIndex === steps.length - 1

  const goToStep = useCallback(
    (stepId: StepId) => {
      const nextIndex = steps.findIndex((step) => step.id === stepId)
      if (nextIndex >= 0) {
        setActiveIndex(nextIndex)
      }
    },
    [steps]
  )

  useImperativeHandle(navigationRef, () => ({ goToStep }), [goToStep])

  function handleNext() {
    if (!validateStep(activeStep.id)) {
      return
    }
    setActiveIndex((current) => Math.min(current + 1, steps.length - 1))
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <WizardProgress activeIndex={activeIndex} onPreviousStep={goToStep} steps={steps} />

      <div>{children(activeStep.id)}</div>

      <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center">
        {activeIndex > 0 ? (
          <Button
            className="w-full sm:w-auto"
            disabled={isSubmitting}
            onClick={() => {
              setActiveIndex((current) => Math.max(current - 1, 0))
            }}
            type="button"
            variant="outline"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            Back
          </Button>
        ) : null}

        <div className="flex flex-col-reverse gap-2 sm:ml-auto sm:flex-row sm:justify-end">
          <Button
            className="w-full sm:w-auto"
            disabled={isSubmitting}
            render={<Link to={cancelTo} />}
            type="button"
            variant="ghost"
          >
            {cancelLabel}
          </Button>
          {isFinalStep ? (
            <Button
              className="w-full sm:w-auto"
              disabled={isSubmitting || disableSubmit}
              form={form}
              key="submit"
              type="submit"
            >
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
          ) : (
            <Button
              className="w-full sm:w-auto"
              disabled={isSubmitting}
              key="next"
              onClick={(event) => {
                event.preventDefault()
                handleNext()
              }}
              type="button"
            >
              Next
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function WizardProgress<StepId extends string>({
  activeIndex,
  onPreviousStep,
  steps,
}: {
  activeIndex: number
  onPreviousStep: (stepId: StepId) => void
  steps: readonly [FormWizardStep<StepId>, ...FormWizardStep<StepId>[]]
}) {
  const activeStep = steps[activeIndex] ?? steps[0]

  return (
    <nav aria-label="Form progress">
      <div className="sm:hidden" aria-live="polite">
        <p className="text-muted-foreground text-xs">
          Step {activeIndex + 1} of {steps.length}
        </p>
        <p className="mt-1 text-sm font-medium">
          {activeStep.title}
          {activeStep.optional ? (
            <span className="text-muted-foreground font-normal"> (Optional)</span>
          ) : null}
        </p>
        {activeStep.description ? (
          <p className="text-muted-foreground mt-1 text-sm">{activeStep.description}</p>
        ) : null}
      </div>

      <ol className="hidden sm:flex">
        {steps.map((step, index) => {
          const isComplete = index < activeIndex
          const isCurrent = index === activeIndex
          const content = (
            <>
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs",
                  isComplete && "border-primary bg-primary text-primary-foreground",
                  isCurrent && "border-primary bg-primary/10 text-primary ring-primary/20 ring-4",
                  !isComplete && !isCurrent && "bg-background text-muted-foreground"
                )}
              >
                {isComplete ? <CheckIcon className="size-3.5" /> : index + 1}
              </span>
              <span className="min-w-0 text-left">
                <span
                  className={cn(
                    "block text-sm leading-snug whitespace-normal",
                    isCurrent ? "text-foreground font-medium" : "text-muted-foreground"
                  )}
                >
                  {step.title}
                </span>
                {step.optional ? (
                  <span className="text-muted-foreground block text-xs">Optional</span>
                ) : null}
              </span>
            </>
          )

          return (
            <li className="flex min-w-0 flex-1 items-center" key={step.id}>
              {isComplete ? (
                <button
                  aria-label={`Return to ${step.title}`}
                  className="focus-visible:ring-ring flex min-w-0 items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                  onClick={() => {
                    onPreviousStep(step.id)
                  }}
                  type="button"
                >
                  {content}
                </button>
              ) : (
                <div
                  aria-current={isCurrent ? "step" : undefined}
                  className="flex min-w-0 items-center gap-2.5"
                >
                  {content}
                </div>
              )}
              {index < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={cn(
                    "bg-border mx-3 h-px min-w-4 flex-1",
                    isComplete && "bg-primary/50"
                  )}
                />
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
