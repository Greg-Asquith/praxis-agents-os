// apps/web/src/features/auth/components/two-factor-verification-form.tsx

import { useState, type SyntheticEvent } from "react"
import { ShieldCheckIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { totpVerificationRequest, useVerifyTotpMutation } from "@/features/auth/api/totp"
import { TotpCodeInput } from "@/features/auth/components/totp-code-input"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function TwoFactorVerificationForm({ onVerified }: { onVerified: () => void }) {
  const verifyMutation = useVerifyTotpMutation()
  const [error, setError] = useState<string | null>(null)
  const [useBackupCode, setUseBackupCode] = useState(false)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const code = formString(new FormData(event.currentTarget), "code").trim()

    verifyMutation.mutate(totpVerificationRequest(code), {
      onSuccess: onVerified,
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
      },
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FieldGroup>
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Verification Failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <Alert>
            <ShieldCheckIcon />
            <AlertTitle>Sign-In Accepted</AlertTitle>
            <AlertDescription>
              {useBackupCode
                ? "Enter one of your saved backup codes to finish signing in."
                : "Enter the code from your authenticator app to finish signing in."}
            </AlertDescription>
          </Alert>
        )}

        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="two-factor-code">
            {useBackupCode ? "Backup code" : "Authenticator code"}
          </FieldLabel>
          <TotpCodeInput
            disabled={verifyMutation.isPending}
            id="two-factor-code"
            invalid={Boolean(error)}
            key={useBackupCode ? "backup" : "authenticator"}
            length={useBackupCode ? 8 : 6}
            name="code"
            required
          />
          <FieldDescription>
            {useBackupCode
              ? "Each backup code works once."
              : "Enter the six-digit code shown in your authenticator app."}
          </FieldDescription>
          <Button
            className="h-auto self-start px-0"
            disabled={verifyMutation.isPending}
            onClick={() => {
              setUseBackupCode((current) => !current)
              setError(null)
            }}
            type="button"
            variant="link"
          >
            {useBackupCode ? "Use an authenticator code" : "Use a backup code"}
          </Button>
        </Field>

        <Button className="h-10 w-full" disabled={verifyMutation.isPending} type="submit">
          <ShieldCheckIcon data-icon="inline-start" />
          {verifyMutation.isPending ? "Verifying" : "Verify and Sign In"}
        </Button>
      </FieldGroup>
    </form>
  )
}
