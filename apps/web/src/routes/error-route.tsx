// apps/web/src/routes/error-route.tsx

import { ArrowLeftIcon, HouseIcon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { getErrorMessage } from "@/lib/api/errors"
import { currentPathname, isAuthRecoveryPath } from "@/routes/recovery-paths"
import { RouteStatusPage } from "@/routes/route-status-page"

export function ErrorRoute({ error }: { error: unknown }) {
  const pathname = currentPathname()
  const authRecovery = isAuthRecoveryPath(pathname)

  return (
    <RouteStatusPage
      actions={
        <>
          <Button
            onClick={() => {
              window.location.reload()
            }}
          >
            <RefreshCwIcon data-icon="inline-start" />
            Try Again
          </Button>
          {authRecovery ? <BackToSignInButton /> : <AppRecoveryActions />}
        </>
      }
      code="500"
      description="Something unexpected interrupted this page. Your work should still be safe, and a fresh attempt will often get things moving again."
      detail={getErrorMessage(error)}
      icon={<TriangleAlertIcon className="size-5" />}
      title="We hit a snag"
    />
  )
}

function BackToSignInButton() {
  return (
    <Button
      variant="outline"
      onClick={() => {
        window.location.assign("/login")
      }}
    >
      <ArrowLeftIcon data-icon="inline-start" />
      Back to Sign In
    </Button>
  )
}

function AppRecoveryActions() {
  return (
    <>
      <Button
        variant="outline"
        onClick={() => {
          window.location.assign("/")
        }}
      >
        <HouseIcon data-icon="inline-start" />
        Go Home
      </Button>
    </>
  )
}
