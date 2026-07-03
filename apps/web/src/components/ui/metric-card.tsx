// apps/web/src/components/ui/metric-card.tsx

import type { ComponentProps, ReactNode } from "react"

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

type MetricCardProps = Omit<ComponentProps<typeof Card>, "children"> & {
  description: ReactNode
  icon?: ReactNode
  title: ReactNode
}

function MetricCard({ description, icon, size = "sm", title, ...props }: MetricCardProps) {
  return (
    <Card size={size} {...props}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {icon}
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  )
}

export { MetricCard }
export type { MetricCardProps }
