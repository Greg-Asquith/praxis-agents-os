// apps/web/src/routes/not-found.tsx

import { Button } from "@/components/ui/button"
import { currentPathname, isAuthRecoveryPath } from "@/routes/recovery-paths"

export function NotFoundRoute() {
  const authRecovery = isAuthRecoveryPath(currentPathname())

  return (
    <main className="bg-background flex min-h-screen items-center justify-center p-6">
      <div className="flex max-w-sm flex-col items-start gap-4">
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">404</p>
          <h1 className="font-heading text-2xl font-semibold">Page not found</h1>
          <p className="text-muted-foreground text-sm">The page you opened is not available.</p>
        </div>
        <Button
          onClick={() => {
            window.location.assign(authRecovery ? "/login" : "/")
          }}
        >
          {authRecovery ? "Back to sign in" : "Go to overview"}
        </Button>
      </div>
    </main>
  )
}
