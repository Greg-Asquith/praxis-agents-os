// apps/web/src/routes/error-route.tsx

import { AlertCircleIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { getErrorMessage } from "@/lib/api/errors"

export function ErrorRoute({ error }: { error: unknown }) {
  return (
    <main className="bg-background flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col gap-4">
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Unable to load this page</AlertTitle>
          <AlertDescription>{getErrorMessage(error)}</AlertDescription>
        </Alert>
        <Button
          variant="outline"
          onClick={() => {
            window.location.assign("/login")
          }}
        >
          Back to sign in
        </Button>
      </div>
    </main>
  )
}
