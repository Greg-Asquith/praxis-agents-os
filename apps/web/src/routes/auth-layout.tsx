// apps/web/src/routes/auth-layout.tsx

import { Outlet } from "@tanstack/react-router"

import { AuthBrandMark, AuthBrandPanel } from "@/features/auth/components/auth-brand-panel"

export function AuthLayoutRoute() {
  return (
    <main className="bg-background grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)]">
      <AuthBrandPanel />
      <section className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-md">
          <AuthBrandMark className="mb-8 justify-center lg:hidden" />
          <Outlet />
        </div>
      </section>
    </main>
  )
}
