// apps/web/src/features/workspaces/routes/accept-invitation-route.tsx

import { getRouteApi } from "@tanstack/react-router"
import { CheckCircle2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useLogoutMutation } from "@/features/auth/api/logout"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

const routeApi = getRouteApi("/app/invitations/accept")

export function AcceptInvitationRoute() {
  const { setWorkspaceBySlug } = useActiveWorkspace()
  const logoutMutation = useLogoutMutation()
  const { token } = routeApi.useSearch()
  const { error, errorReason, result } = routeApi.useLoaderData()
  const successTitle = result?.status === "accepted" ? "Invitation accepted" : "Workspace joined"

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="min-w-0">
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

          {result ? (
            <Alert>
              <CheckCircle2Icon className="size-4" />
              <AlertTitle>{successTitle}</AlertTitle>
              <AlertDescription>
                {result.workspace.name} is available in your workspace switcher.
              </AlertDescription>
            </Alert>
          ) : null}

          {errorReason === "invitation_email_mismatch" ? (
            <Button
              className="w-fit"
              disabled={logoutMutation.isPending}
              type="button"
              variant="outline"
              onClick={() => {
                logoutMutation.mutate(undefined, {
                  onSuccess: () => {
                    const invitePath = `/invitations/accept${token ? `?token=${encodeURIComponent(token)}` : ""}`
                    window.location.replace(`/login?redirect=${encodeURIComponent(invitePath)}`)
                  },
                })
              }}
            >
              {logoutMutation.isPending ? "Signing out" : "Sign out and switch account"}
            </Button>
          ) : null}

          {result ? (
            <Button
              className="w-fit"
              type="button"
              onClick={() => {
                setWorkspaceBySlug(result.workspace.slug)
              }}
            >
              Switch to This Workspace
            </Button>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
