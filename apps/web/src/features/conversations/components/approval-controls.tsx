// apps/web/src/features/conversations/components/approval-controls.tsx

import { useState, type SyntheticEvent } from "react"
import { ShieldCheckIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { safeJsonPreview } from "@/features/conversations/message-parts"
import type {
  AgentRunResumeDecision,
  PendingToolApproval,
} from "@/features/conversations/types"

type LocalDecision = {
  decision: "approved" | "denied"
  message: string
  overrideArgs: string
}

const DEFAULT_DECISION: LocalDecision = {
  decision: "denied",
  message: "",
  overrideArgs: "",
}

export function ApprovalControls({
  approvals,
  error,
  isLoading,
  isSubmitting,
  onSubmit,
}: {
  approvals: PendingToolApproval[]
  error: string | null
  isLoading: boolean
  isSubmitting: boolean
  onSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
}) {
  const [decisions, setDecisions] = useState<Record<string, LocalDecision>>({})
  const [formError, setFormError] = useState<string | null>(null)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const payload = buildResumeDecisions(approvals, decisions)
    if (typeof payload === "string") {
      setFormError(payload)
      return
    }

    try {
      await onSubmit(payload)
    } catch (submitError) {
      setFormError(submitError instanceof Error ? submitError.message : "Approval submit failed.")
    }
  }

  if (approvals.length === 0 && !isLoading && !error) {
    return null
  }

  return (
    <form
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheckIcon className="size-4" />
            Approval decisions
          </CardTitle>
          <CardDescription>
            Review every pending tool call before resuming this run.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Approval state unavailable</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {formError && (
              <Alert variant="destructive">
                <AlertTitle>Run not resumed</AlertTitle>
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
            {isLoading && (
              <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-sm">
                Loading pending approvals.
              </p>
            )}
            {approvals.map((approval) => {
              const decision = decisions[approval.tool_call_id] ?? DEFAULT_DECISION

              return (
                <div className="grid gap-3 rounded-lg border p-3" key={approval.tool_call_id}>
                  <div className="flex flex-col justify-between gap-2 md:flex-row md:items-start">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium">{approval.name}</p>
                        <Badge variant="outline">{approval.tool_call_id}</Badge>
                      </div>
                      <pre className="bg-muted text-muted-foreground mt-2 max-h-48 overflow-auto rounded-lg p-3 text-xs">
                        {safeJsonPreview(approval.args)}
                      </pre>
                    </div>
                    <Select
                      onValueChange={(value) => {
                        setDecision(approval.tool_call_id, {
                          ...decision,
                          decision: value === "approved" ? "approved" : "denied",
                        })
                      }}
                      value={decision.decision}
                    >
                      <SelectTrigger className="w-full md:w-36" size="sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent align="end">
                        <SelectGroup>
                          <SelectItem value="denied">Deny</SelectItem>
                          <SelectItem value="approved">Approve</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>

                  {decision.decision === "approved" ? (
                    <Field>
                      <FieldLabel htmlFor={`${approval.tool_call_id}-override`}>
                        Override args
                      </FieldLabel>
                      <Textarea
                        className="min-h-24 font-mono text-xs"
                        id={`${approval.tool_call_id}-override`}
                        onChange={(event) => {
                          setDecision(approval.tool_call_id, {
                            ...decision,
                            overrideArgs: event.currentTarget.value,
                          })
                        }}
                        placeholder="Optional JSON object"
                        value={decision.overrideArgs}
                      />
                      <FieldDescription>
                        Leave blank to approve the tool call with its original args.
                      </FieldDescription>
                    </Field>
                  ) : (
                    <Field>
                      <FieldLabel htmlFor={`${approval.tool_call_id}-message`}>
                        Denial message
                      </FieldLabel>
                      <Textarea
                        className="min-h-20"
                        id={`${approval.tool_call_id}-message`}
                        onChange={(event) => {
                          setDecision(approval.tool_call_id, {
                            ...decision,
                            message: event.currentTarget.value,
                          })
                        }}
                        placeholder="Optional message for the agent"
                        value={decision.message}
                      />
                    </Field>
                  )}
                </div>
              )
            })}
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-end">
          <Button disabled={approvals.length === 0 || isLoading || isSubmitting} type="submit">
            <ShieldCheckIcon data-icon="inline-start" />
            {isSubmitting ? "Resuming" : "Resume run"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  )

  function setDecision(toolCallId: string, decision: LocalDecision) {
    setDecisions((current) => ({ ...current, [toolCallId]: decision }))
  }
}

function buildResumeDecisions(
  approvals: PendingToolApproval[],
  decisions: Record<string, LocalDecision>
): AgentRunResumeDecision[] | string {
  const payload: AgentRunResumeDecision[] = []

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id]
    const effectiveDecision = decision ?? DEFAULT_DECISION

    if (effectiveDecision.decision === "denied") {
      payload.push({
        decision: "denied",
        message: effectiveDecision.message.trim() || null,
        tool_call_id: approval.tool_call_id,
      })
      continue
    }

    const overrideArgs = parseOverrideArgs(effectiveDecision.overrideArgs)
    if (typeof overrideArgs === "string") {
      return overrideArgs
    }

    payload.push({
      decision: "approved",
      override_args: overrideArgs,
      tool_call_id: approval.tool_call_id,
    })
  }

  return payload
}

function parseOverrideArgs(value: string): Record<string, unknown> | null | string {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }

  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return "Override args must be a JSON object."
    }
    return parsed as Record<string, unknown>
  } catch {
    return "Override args must be valid JSON."
  }
}
