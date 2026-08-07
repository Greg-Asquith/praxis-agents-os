// apps/web/src/features/auth/routes/profile-route.tsx

import { Suspense } from "react"
import { useQuery } from "@tanstack/react-query"

import { PageHeader } from "@/components/shell/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import { PasswordForm } from "@/features/auth/components/password-form"
import { ProfileForm } from "@/features/auth/components/profile-form"
import { SignInMethods } from "@/features/auth/components/sign-in-methods"
import { TwoFactorSection } from "@/features/auth/components/two-factor-section"

export function ProfileRoute() {
  const providersQuery = useQuery(oauthProvidersQueryOptions())
  const emailAuthEnabled =
    providersQuery.isError || providersQuery.data?.email_auth_enabled === true

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <PageHeader
        description={
          emailAuthEnabled
            ? "Manage your account details, password, and security."
            : "Manage your account details and security."
        }
        title="Profile settings"
      />

      <ProfileForm />

      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <SignInMethods emailAuthEnabled={emailAuthEnabled} />
      </Suspense>

      {emailAuthEnabled && <PasswordForm />}
      <TwoFactorSection emailAuthEnabled={emailAuthEnabled} />
    </div>
  )
}
