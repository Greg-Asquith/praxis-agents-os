// apps/web/src/features/auth/routes/profile-route.tsx

import { Suspense } from "react"

import { PageHeader } from "@/components/shell/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { PasswordForm } from "@/features/auth/components/password-form"
import { ProfileForm } from "@/features/auth/components/profile-form"
import { SignInMethods } from "@/features/auth/components/sign-in-methods"
import { TwoFactorSection } from "@/features/auth/components/two-factor-section"

export function ProfileRoute() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <PageHeader
        description="Manage your account details, password, and security."
        title="Profile settings"
      />

      <ProfileForm />

      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <SignInMethods />
      </Suspense>

      <PasswordForm />
      <TwoFactorSection />
    </div>
  )
}
