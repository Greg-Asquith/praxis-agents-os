// apps/web/src/features/auth/components/auth-brand-panel.tsx

import { appConfig } from "@/config/app"
import { cn } from "@/lib/utils"

export function AuthBrandMark({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="bg-primary/10 text-primary flex size-8 items-center justify-center rounded-lg text-sm font-semibold">
        P
      </div>
      <span className="font-heading text-sm font-medium">{appConfig.name}</span>
    </div>
  )
}

export function AuthBrandPanel() {
  return (
    <section className="bg-sidebar text-sidebar-foreground relative hidden overflow-hidden border-r p-8 lg:flex lg:flex-col lg:justify-between">
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-80 dark:opacity-100"
        style={{
          backgroundImage:
            "radial-gradient(circle at 82% 12%, color-mix(in oklch, var(--primary) 15%, transparent) 0%, transparent 42%), radial-gradient(circle at 12% 72%, color-mix(in oklch, var(--link) 10%, transparent) 0%, transparent 38%), radial-gradient(circle at 68% 78%, color-mix(in oklch, var(--agent-6) 8%, transparent) 0%, transparent 34%)",
        }}
      />

      <div
        aria-hidden="true"
        className="text-muted-foreground absolute inset-x-[4%] top-[8%] bottom-[16%] opacity-60 dark:opacity-75"
        style={{
          maskImage: "radial-gradient(ellipse at center, black 38%, transparent 76%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 38%, transparent 76%)",
        }}
      >
        <svg className="size-full" viewBox="0 0 900 700">
          <g fill="none" stroke="currentColor" strokeWidth="1.25">
            <ellipse cx="490" cy="340" rx="335" ry="132" transform="rotate(-14 490 340)" />
            <ellipse
              cx="490"
              cy="340"
              rx="270"
              ry="235"
              strokeDasharray="560 180"
              transform="rotate(24 490 340)"
            />
            <ellipse
              cx="490"
              cy="340"
              rx="198"
              ry="300"
              strokeDasharray="430 220"
              transform="rotate(58 490 340)"
            />
            <circle cx="490" cy="340" r="108" strokeDasharray="320 90" />
          </g>

          <g>
            <circle cx="180" cy="293" r="7" fill="var(--agent-1)" />
            <circle cx="320" cy="148" r="6" fill="var(--agent-2)" />
            <circle cx="597" cy="123" r="8" fill="var(--agent-3)" />
            <circle cx="785" cy="302" r="6" fill="var(--agent-4)" />
            <circle cx="692" cy="498" r="7" fill="var(--agent-5)" />
            <circle cx="425" cy="566" r="6" fill="var(--agent-6)" />
            <circle cx="298" cy="445" r="8" fill="var(--agent-7)" />
            <circle cx="528" cy="326" r="7" fill="var(--agent-8)" />
          </g>
        </svg>
      </div>

      <div
        aria-hidden="true"
        className="from-sidebar via-sidebar/90 absolute inset-x-0 bottom-0 h-2/5 bg-linear-to-t to-transparent"
      />

      <AuthBrandMark className="relative z-10" />

      <div className="relative z-10 max-w-xl">
        <p className="text-muted-foreground text-sm font-medium">
          The Operating Intelligence Layer
        </p>
        <h1 className="font-heading mt-3 max-w-lg text-3xl font-semibold tracking-normal">
          An AI Operating System that remembers your work, respects your rules, and acts on the real
          systems your team uses.
        </h1>
      </div>
    </section>
  )
}
