// apps/web/src/features/auth/components/two-factor-section.tsx

import { useState, type SyntheticEvent } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"
import { QRCodeSVG } from "qrcode.react"
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
import { Input } from "@/components/ui/input"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import {
  useDisableTotpMutation,
  useEnableTotpMutation,
  useSetupTotpMutation,
} from "@/features/auth/api/totp"
import type { TotpSetupResponse } from "@/features/auth/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function TwoFactorSection() {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const setupMutation = useSetupTotpMutation()
  const enableMutation = useEnableTotpMutation()
  const disableMutation = useDisableTotpMutation()

  const [setup, setSetup] = useState<TotpSetupResponse | null>(null)
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [disabling, setDisabling] = useState(false)

  function startSetup() {
    setError(null)
    setBackupCodes(null)
    setupMutation.mutate(undefined, {
      onSuccess: (response) => {
        setSetup(response)
      },
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
      },
    })
  }

  function cancelSetup() {
    setSetup(null)
    setError(null)
  }

  function handleEnable(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const token = formString(new FormData(event.currentTarget), "token").trim()
    enableMutation.mutate(token, {
      onSuccess: (response) => {
        setSetup(null)
        setBackupCodes(response.backup_codes)
      },
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
      },
    })
  }

  function handleDisable(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const token = formString(new FormData(event.currentTarget), "token").trim()
    disableMutation.mutate(
      { token },
      {
        onSuccess: () => {
          setDisabling(false)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheckIcon className="size-4" />
          Two-factor authentication
          {user.totp_enabled && <Badge variant="secondary">Enabled</Badge>}
        </CardTitle>
        <CardDescription>
          Require a one-time code from an authenticator app when you sign in.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <FieldGroup>
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Something went wrong</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {backupCodes && (
            <Alert>
              <AlertTitle>Save your backup codes</AlertTitle>
              <AlertDescription>
                Store these somewhere safe. Each code can be used once if you lose your
                authenticator. They won&apos;t be shown again.
                <code className="bg-muted mt-2 grid grid-cols-2 gap-1 rounded-md p-3 font-mono text-xs">
                  {backupCodes.map((code) => (
                    <span key={code}>{code}</span>
                  ))}
                </code>
              </AlertDescription>
            </Alert>
          )}

          {/* Enabled, not mid-disable: offer disable */}
          {user.totp_enabled && !disabling && !backupCodes && (
            <p className="text-muted-foreground text-sm">
              Two-factor authentication is on for your account.
            </p>
          )}

          {/* Disable flow */}
          {user.totp_enabled && disabling && (
            <form id="totp-disable-form" onSubmit={handleDisable}>
              <Field>
                <FieldLabel htmlFor="totp-disable-token">Authenticator or backup code</FieldLabel>
                <Input
                  autoComplete="one-time-code"
                  id="totp-disable-token"
                  inputMode="numeric"
                  name="token"
                  required
                />
                <FieldDescription>
                  Enter a current code to confirm turning two-factor off.
                </FieldDescription>
              </Field>
            </form>
          )}

          {/* Setup flow: QR + verify */}
          {!user.totp_enabled && setup && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
                <div className="rounded-lg border bg-white p-3">
                  <QRCodeSVG value={setup.provisioning_uri} size={144} />
                </div>
                <div className="flex min-w-0 flex-col gap-1">
                  <p className="text-sm font-medium">Scan with an authenticator app</p>
                  <p className="text-muted-foreground text-xs">Or enter this secret manually:</p>
                  <code className="bg-muted rounded-md px-2 py-1 font-mono text-xs break-all">
                    {setup.secret}
                  </code>
                </div>
              </div>
              <form id="totp-enable-form" onSubmit={handleEnable}>
                <Field>
                  <FieldLabel htmlFor="totp-enable-token">Verification code</FieldLabel>
                  <Input
                    autoComplete="one-time-code"
                    id="totp-enable-token"
                    inputMode="numeric"
                    name="token"
                    placeholder="123456"
                    required
                  />
                </Field>
              </form>
            </div>
          )}
        </FieldGroup>
      </CardContent>

      <CardFooter className="gap-3">
        {!user.totp_enabled && !setup && (
          <Button disabled={setupMutation.isPending} onClick={startSetup} type="button">
            {setupMutation.isPending ? "Preparing" : "Set up two-factor"}
          </Button>
        )}

        {!user.totp_enabled && setup && (
          <>
            <Button disabled={enableMutation.isPending} form="totp-enable-form" type="submit">
              {enableMutation.isPending ? "Verifying" : "Verify and enable"}
            </Button>
            <Button onClick={cancelSetup} type="button" variant="outline">
              Cancel
            </Button>
          </>
        )}

        {user.totp_enabled && !disabling && (
          <Button
            onClick={() => {
              setDisabling(true)
            }}
            type="button"
            variant="destructive"
          >
            Turn off
          </Button>
        )}

        {user.totp_enabled && disabling && (
          <>
            <Button
              disabled={disableMutation.isPending}
              form="totp-disable-form"
              type="submit"
              variant="destructive"
            >
              {disableMutation.isPending ? "Turning off" : "Confirm turn off"}
            </Button>
            <Button
              onClick={() => {
                setDisabling(false)
              }}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
          </>
        )}
      </CardFooter>
    </Card>
  )
}
