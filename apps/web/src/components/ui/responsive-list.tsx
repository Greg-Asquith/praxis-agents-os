// apps/web/src/components/ui/responsive-list.tsx

import * as React from "react"

import { cn } from "@/lib/utils"

function ResponsiveList({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="responsive-list"
      role="list"
      className={cn("divide-y md:hidden", className)}
      {...props}
    />
  )
}

function ResponsiveListItem({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="responsive-list-item"
      role="listitem"
      className={cn(
        "py-3 text-sm [contain-intrinsic-size:auto_96px] [content-visibility:auto]",
        className
      )}
      {...props}
    />
  )
}

function ResponsiveListMeta({
  children,
  className,
  label,
  ...props
}: React.ComponentProps<"div"> & { label: string }) {
  return (
    <div data-slot="responsive-list-meta" className={cn("min-w-0", className)} {...props}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 min-w-0 wrap-break-word">{children}</dd>
    </div>
  )
}

export { ResponsiveList, ResponsiveListItem, ResponsiveListMeta }
