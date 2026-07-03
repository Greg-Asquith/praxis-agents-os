// apps/web/src/features/skills/components/skill-form-section.tsx

import type { ReactNode } from "react"

export function SkillFormSection({
  children,
  description,
  eyebrow,
  title,
}: {
  children: ReactNode
  description: string
  eyebrow: string
  title: string
}) {
  return (
    <section className="bg-card rounded-md border p-4">
      <div className="mb-4 flex flex-col gap-1">
        <p className="text-muted-foreground text-xs font-medium">{eyebrow}</p>
        <h2 className="font-heading text-lg font-semibold tracking-normal">{title}</h2>
        <p className="text-muted-foreground max-w-3xl text-sm">{description}</p>
      </div>

      {children}
    </section>
  )
}
