// apps/web/src/routes/tools.tsx

import { Link } from "@tanstack/react-router"
import { ChevronRightIcon, WrenchIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { EmptyState } from "@/components/ui/empty-state"
import { useCustomTools } from "@/custom"

export function ToolsRoute() {
  const tools = useCustomTools()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Tools" description="Tools for your team's work." />
      {tools.length > 0 ? (
        <div className="divide-border divide-y" aria-label="Tools">
          {tools.map((tool) => {
            const Icon = tool.icon

            return (
              <Link
                key={tool.to}
                className="focus-visible:ring-ring/50 group hover:bg-muted/45 flex min-h-24 items-center gap-3 rounded-lg px-2 py-4 transition-colors outline-none focus-visible:ring-[3px] sm:gap-4 sm:px-3"
                to={tool.to}
              >
                <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{tool.title}</span>
                  <span className="text-muted-foreground mt-0.5 block text-sm">
                    {tool.description}
                  </span>
                </span>
                <ChevronRightIcon
                  className="text-muted-foreground size-4 shrink-0 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Link>
            )
          })}
        </div>
      ) : (
        <EmptyState
          icon={<WrenchIcon className="size-5" aria-hidden="true" />}
          title="No Tools Yet"
          description="Tools built for your team appear here."
        />
      )}
    </div>
  )
}
