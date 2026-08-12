// apps/web/src/routes/route-status-page.tsx

import type { ReactNode } from "react"

import { AuthBrandMark } from "@/features/auth/components/auth-brand-panel"

type RouteStatusPageProps = {
  actions: ReactNode
  code: string
  description: string
  detail?: string
  icon: ReactNode
  title: string
}

export function RouteStatusPage({
  actions,
  code,
  description,
  detail,
  icon,
  title,
}: RouteStatusPageProps) {
  return (
    <main className="bg-background relative flex min-h-dvh overflow-hidden">
      <RouteStatusBackdrop />

      <div className="relative mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-6 py-6 sm:px-10 sm:py-8">
        <AuthBrandMark />

        <section className="flex flex-1 items-center py-12 sm:py-16">
          <div className="grid w-full items-center gap-10 md:grid-cols-[minmax(14rem,0.7fr)_minmax(0,1fr)] md:gap-16 lg:gap-24">
            <div aria-hidden="true" className="relative hidden aspect-square md:block">
              <div className="border-border absolute inset-[8%] rounded-full border" />
              <div className="border-border absolute inset-[21%] rotate-12 rounded-full border" />
              <div className="bg-primary/10 absolute inset-[32%] rounded-full" />
              <div className="bg-agent-2 absolute top-[15%] left-[27%] size-2.5 rounded-full" />
              <div className="bg-agent-6 absolute right-[13%] bottom-[29%] size-2 rounded-full" />
              <div className="bg-agent-8 absolute bottom-[12%] left-[31%] size-2 rounded-full" />
              <p className="font-heading text-foreground absolute inset-0 flex items-center justify-center text-7xl font-semibold tracking-tighter lg:text-8xl">
                {code}
              </p>
            </div>

            <div className="flex max-w-xl flex-col items-start">
              <div className="bg-primary/10 text-primary flex size-11 items-center justify-center rounded-xl">
                {icon}
              </div>
              <p className="text-primary mt-6 text-sm font-medium md:hidden">Error {code}</p>
              <h1 className="font-heading mt-2 text-3xl font-semibold tracking-tight sm:text-4xl md:mt-6">
                {title}
              </h1>
              <p className="text-muted-foreground mt-3 max-w-lg text-base leading-relaxed">
                {description}
              </p>
              {detail ? (
                <p className="bg-muted/60 text-muted-foreground mt-5 max-w-lg rounded-lg border px-3 py-2 text-sm">
                  {detail}
                </p>
              ) : null}
              <div className="mt-7 flex flex-wrap gap-2">{actions}</div>
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

function RouteStatusBackdrop() {
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
