// apps/web/src/routes/not-found.tsx

import { ArrowLeftIcon, HouseIcon, SearchXIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { currentPathname, isAuthRecoveryPath } from "@/routes/recovery-paths"
import { RouteStatusPage } from "@/routes/route-status-page"

export function NotFoundRoute() {
  const authRecovery = isAuthRecoveryPath(currentPathname())

  return (
    <RouteStatusPage
      actions={
        <>
          <Button
            onClick={() => {
              window.location.assign(authRecovery ? "/login" : "/")
            }}
          >
            {authRecovery ? (
              <ArrowLeftIcon data-icon="inline-start" />
            ) : (
              <HouseIcon data-icon="inline-start" />
            )}
            {authRecovery ? "Back to Sign In" : "Go Home"}
          </Button>
          {!authRecovery ? (
            <Button
              variant="outline"
              onClick={() => {
                window.history.back()
              }}
            >
              <ArrowLeftIcon data-icon="inline-start" />
              Go Back
            </Button>
          ) : null}
        </>
      }
      code="404"
      description="The page may have moved, been removed, or never existed. You can return to a familiar place and keep working."
      icon={<SearchXIcon className="size-5" />}
      title="This page is out of reach"
    />
  )
}
