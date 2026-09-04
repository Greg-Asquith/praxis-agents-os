// apps/web/src/routes/pending.tsx

import { AuthBrandMark } from "@/features/auth/components/auth-brand-panel"

export function PendingRoute() {
  return (
    <main className="bg-background relative flex min-h-dvh overflow-hidden">
      <StartupBackdrop />

      <div className="relative mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-6 py-6 sm:px-10 sm:py-8">
        <AuthBrandMark />

        <section className="flex flex-1 items-center justify-center py-12 sm:py-16">
          <div
            aria-atomic="true"
            aria-live="polite"
            className="flex max-w-lg flex-col items-center text-center"
            role="status"
          >
            <StartupOrbit />

            <p className="text-primary mt-8 text-sm font-medium">Starting up</p>
            <h1 className="font-heading mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              The system is getting ready
            </h1>
            <p className="text-muted-foreground mt-4 max-w-md text-base leading-relaxed">
              This can take a few seconds after a period of inactivity. This page continues
              automatically when everything is ready.
            </p>

            <div
              aria-hidden="true"
              className="bg-muted mt-7 flex items-center gap-1.5 rounded-full px-3 py-2"
            >
              <span className="bg-agent-2 size-1.5 animate-pulse rounded-full motion-reduce:animate-none" />
              <span className="bg-primary size-1.5 animate-pulse rounded-full [animation-delay:200ms] motion-reduce:animate-none" />
              <span className="bg-agent-6 size-1.5 animate-pulse rounded-full [animation-delay:400ms] motion-reduce:animate-none" />
            </div>
          </div>
        </section>

        <p className="text-muted-foreground text-xs">
          A safe place for your agents to do real work.
        </p>
      </div>
    </main>
  )
}

function StartupOrbit() {
  return (
    <div
      aria-hidden="true"
      className="relative flex size-32 items-center justify-center sm:size-36"
    >
      <div className="bg-primary/10 absolute inset-5 rounded-full blur-xl" />
      <div className="border-border absolute inset-0 rounded-full border" />
      <div className="border-border absolute inset-4 rotate-12 rounded-full border" />

      <div className="animation-duration-[5s] absolute inset-0 animate-spin motion-reduce:animate-none">
        <span className="bg-agent-2 absolute top-1/2 left-0 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" />
        <span className="bg-agent-6 absolute top-0 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full" />
        <span className="bg-agent-8 absolute right-[7%] bottom-[14%] size-2 -translate-y-1/2 rounded-full" />
      </div>

      <div className="bg-card text-primary ring-border relative flex size-16 items-center justify-center rounded-2xl text-xl font-semibold shadow-sm ring-1">
        P
      </div>
    </div>
  )
}

function StartupBackdrop() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 opacity-80"
      style={{
        backgroundImage:
          "radial-gradient(circle at 16% 18%, color-mix(in oklch, var(--primary) 10%, transparent) 0%, transparent 30%), radial-gradient(circle at 86% 78%, color-mix(in oklch, var(--link) 7%, transparent) 0%, transparent 28%)",
      }}
    />
  )
}
