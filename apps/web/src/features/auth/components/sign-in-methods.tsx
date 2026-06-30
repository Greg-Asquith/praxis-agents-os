// apps/web/src/features/auth/components/sign-in-methods.tsx

import { useSuspenseQuery } from "@tanstack/react-query"
import { CheckIcon, KeyRoundIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { identitiesQueryOptions } from "@/features/auth/api/get-identities"

function providerLabel(provider: string) {
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

export function SignInMethods() {
  const { data } = useSuspenseQuery(identitiesQueryOptions())

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign-in methods</CardTitle>
        <CardDescription>How you can sign in to your account.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col divide-y rounded-lg border">
          <li className="flex items-center justify-between gap-3 px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-medium">
              <KeyRoundIcon className="size-4" />
              Password
            </span>
            {data.has_password ? (
              <Badge variant="secondary">
                <CheckIcon data-icon="inline-start" />
                Set
              </Badge>
            ) : (
              <Badge variant="outline">Not set</Badge>
            )}
          </li>

          {data.identities.map((identity) => (
            <li
              key={`${identity.provider}:${identity.email ?? ""}`}
              className="flex items-center justify-between gap-3 px-4 py-3"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium">{providerLabel(identity.provider)}</span>
                {identity.email && (
                  <span className="text-muted-foreground truncate text-xs">{identity.email}</span>
                )}
              </span>
              {identity.email_verified ? (
                <Badge variant="secondary">
                  <CheckIcon data-icon="inline-start" />
                  Verified
                </Badge>
              ) : (
                <Badge variant="outline">Connected</Badge>
              )}
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground mt-3 text-xs">
          Linking and unlinking sign-in methods isn&apos;t available yet.
        </p>
      </CardContent>
    </Card>
  )
}
