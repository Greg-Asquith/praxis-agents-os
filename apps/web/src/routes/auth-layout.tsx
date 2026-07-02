// apps/web/src/routes/auth-layout.tsx

import { Outlet } from "@tanstack/react-router"

import { appConfig } from "@/config/app"

export function AuthLayoutRoute() {
  return (
    <main className="bg-background grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)]">
      <section className="bg-muted/30 hidden border-r p-8 lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg text-sm font-semibold">
            P
          </div>
          <span className="font-heading text-sm font-medium">{appConfig.name}</span>
        </div>
        <div className="max-w-xl">
          <p className="text-muted-foreground text-sm font-medium">
            The Operating Intelligence Layer
          </p>
          <h1 className="font-heading mt-3 max-w-lg text-3xl font-semibold tracking-normal">
            An AI Operating System that remembers your work, respects your rules, and acts on the
            real systems your team uses.
          </h1>
        </div>
      </section>
      <section className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-md">
          <Outlet />
        </div>
      </section>
    </main>
  )
}
