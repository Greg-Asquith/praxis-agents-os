// apps/web/src/components/forms/form-section.tsx

import type { ReactNode } from "react"

export function FormSection({
  children,
  description,
  eyebrow,
  icon,
  id,
  title,
}: {
  children: ReactNode
  description: string
  eyebrow: string
  icon?: ReactNode
  id?: string
  title: string
}) {
  return (
    <section className="bg-card rounded-md border p-5 sm:p-6" id={id}>
      <div className="mb-6 flex flex-col gap-1.5">
        <p className="text-muted-foreground text-xs font-medium">{eyebrow}</p>
        <h2 className="font-heading flex items-center gap-2 text-lg font-semibold tracking-normal">
          {icon}
          {title}
        </h2>
        <p className="text-muted-foreground max-w-3xl text-sm">{description}</p>
      </div>

      {children}
    </section>
  )
}
