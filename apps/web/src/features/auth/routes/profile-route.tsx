// apps/web/src/features/auth/routes/profile-route.tsx

import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { PasswordForm } from "@/features/auth/components/password-form"
import { ProfileForm } from "@/features/auth/components/profile-form"
import { SignInMethods } from "@/features/auth/components/sign-in-methods"
import { TwoFactorSection } from "@/features/auth/components/two-factor-section"

export function ProfileRoute() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-heading text-2xl font-semibold tracking-normal">Profile settings</h1>
        <p className="text-muted-foreground text-sm">
          Manage your account details, password, and security.
        </p>
      </div>

      <ProfileForm />

      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <SignInMethods />
      </Suspense>

      <PasswordForm />
      <TwoFactorSection />
    </div>
  )
}
