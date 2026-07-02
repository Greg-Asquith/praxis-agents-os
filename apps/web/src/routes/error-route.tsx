// apps/web/src/routes/error-route.tsx

import { AlertCircleIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { getErrorMessage } from "@/lib/api/errors"
import { currentPathname, isAuthRecoveryPath } from "@/routes/recovery-paths"

export function ErrorRoute({ error }: { error: unknown }) {
  const pathname = currentPathname()
  const authRecovery = isAuthRecoveryPath(pathname)

  return (
    <main className="bg-background flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col gap-4">
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Unable to load this page</AlertTitle>
          <AlertDescription>{getErrorMessage(error)}</AlertDescription>
        </Alert>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => {
              window.location.reload()
            }}
          >
            Try Again
          </Button>
          {authRecovery ? <BackToSignInButton /> : <AppRecoveryActions />}
        </div>
      </div>
    </main>
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
        Home
      </Button>
      <Button
        variant="ghost"
        onClick={() => {
          window.location.assign("/profile")
        }}
      >
        Profile Settings
      </Button>
    </>
  )
}
