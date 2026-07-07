// apps/web/src/features/workspaces/routes/accept-invitation-route.tsx

import { useEffect, useRef, useState } from "react"
import { useRouterState } from "@tanstack/react-router"
import { CheckCircle2Icon, Loader2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useAcceptInvitationMutation } from "@/features/workspaces/api/accept-invitation"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import type { WorkspaceInvitationAcceptResponse } from "@/features/workspaces/types"
import { getErrorMessage } from "@/lib/api/errors"

type AcceptInvitationSearch = {
  token?: string
}

type AcceptInvitationState =
  | { token: string; status: "idle" | "pending" }
  | { result: WorkspaceInvitationAcceptResponse; status: "success"; token: string }
  | { error: string; status: "error"; token: string }

const acceptInvitationPromises = new Map<string, Promise<WorkspaceInvitationAcceptResponse>>()

function acceptInvitationOnce(
  token: string,
  acceptInvitation: (payload: { token: string }) => Promise<WorkspaceInvitationAcceptResponse>
) {
  const existing = acceptInvitationPromises.get(token)
  if (existing) {
    return existing
  }

  const promise = acceptInvitation({ token }).finally(() => {
    acceptInvitationPromises.delete(token)
  })
  acceptInvitationPromises.set(token, promise)
  return promise
}

export function AcceptInvitationRoute() {
  const search = useRouterState({
    select: (state): AcceptInvitationSearch => state.location.search,
  })
  const token = search.token?.trim() ?? ""
  const startedTokenRef = useRef<string | null>(null)
  const { setWorkspaceBySlug } = useActiveWorkspace()
  const { mutateAsync: acceptInvitation } = useAcceptInvitationMutation()
  const [invitationState, setInvitationState] = useState<AcceptInvitationState>({
    status: "idle",
    token: "",
  })

  useEffect(() => {
    if (!token) {
      return
    }
    if (startedTokenRef.current === token) {
      return
    }

    startedTokenRef.current = token
    void acceptInvitationOnce(token, acceptInvitation)
      .then((response) => {
        setInvitationState({ result: response, status: "success", token })
      })
      .catch((mutationError: unknown) => {
        setInvitationState({ error: getErrorMessage(mutationError), status: "error", token })
      })
  }, [acceptInvitation, token])

  const activeState = getActiveInvitationState(token, invitationState)
  const result = activeState.status === "success" ? activeState.result : null
  const error = activeState.status === "error" ? activeState.error : null
  const accepting = activeState.status === "pending"
  const successTitle = result?.status === "accepted" ? "Invitation accepted" : "Workspace joined"

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex min-w-0 flex-col gap-2">
        <p className="text-muted-foreground text-sm font-medium">Workspace</p>
        <h1 className="font-heading text-2xl font-semibold tracking-normal">Invitation</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace invitation</CardTitle>
          <CardDescription>
            Accept the invitation and add the workspace to your account.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Invitation not accepted</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {accepting ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2Icon className="size-4 animate-spin" />
              Accepting invitation...
            </div>
          ) : null}

          {result ? (
            <Alert>
              <CheckCircle2Icon className="size-4" />
              <AlertTitle>{successTitle}</AlertTitle>
              <AlertDescription>
                {result.workspace.name} is available in your workspace switcher.
              </AlertDescription>
            </Alert>
          ) : null}

          {result ? (
            <Button
              className="w-fit"
              type="button"
              onClick={() => {
                setWorkspaceBySlug(result.workspace.slug)
              }}
            >
              Switch to this workspace
            </Button>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function getActiveInvitationState(
  token: string,
  state: AcceptInvitationState
): AcceptInvitationState {
  if (!token) {
    return { error: "This invitation link is missing a token.", status: "error", token }
  }
  if (state.token === token && state.status !== "idle") {
    return state
  }
  return { status: "pending", token }
}
