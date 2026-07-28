// apps/web/src/routes/context.tsx

import { Link } from "@tanstack/react-router"
import {
  BrainIcon,
  ChevronRightIcon,
  FileStackIcon,
  FilesIcon,
  Layers3Icon,
  LibraryIcon,
  SparklesIcon,
  type LucideIcon,
} from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"

type ContextSection = {
  description: string
  icon: LucideIcon
  label: string
  to:
    | "/artifacts"
    | "/files"
    | "/integrations/context-groups"
    | "/knowledge"
    | "/memories"
    | "/skills"
  when: string
}

const contextSections: readonly ContextSection[] = [
  {
    label: "Skills",
    to: "/skills",
    icon: SparklesIcon,
    description: "Step-by-step instructions that teach agents how to do a repeatable job your way.",
    when: "Use it when an agent should do a task the same way every time - like producing the weekly report in your format.",
  },
  {
    label: "Knowledge Base",
    to: "/knowledge",
    icon: LibraryIcon,
    description:
      "A searchable library of reference documents agents look up and cite when they answer.",
    when: "Use it for facts agents should check rather than guess - policies, product details, pricing.",
  },
  {
    label: "Memory",
    to: "/memories",
    icon: BrainIcon,
    description: "Details agents have saved while working, so they don't ask twice.",
    when: "Come here to review what agents have remembered, correct anything wrong, and remove what no longer applies.",
  },
  {
    label: "Files",
    to: "/files",
    icon: FilesIcon,
    description:
      "Working documents you and your agents share - things you upload for agents to read and use.",
    when: "Use it for the raw materials of a task - like a spreadsheet to process or a brief to work from.",
  },
  {
    label: "Artifacts",
    to: "/artifacts",
    icon: FileStackIcon,
    description:
      "Finished work agents produce, kept in versions you can review, restore, and share.",
    when: "Come here to find what agents have made - like a report you can send on with a share link.",
  },
  {
    label: "Context Groups",
    to: "/integrations/context-groups",
    icon: Layers3Icon,
    description:
      "Named sets of connected accounts and resources that tell an agent exactly which ones to work with.",
    when: "Use it when different agents or schedules should use different accounts - like one agent per client.",
  },
]

export function ContextRoute() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        description="Everything your agents can draw on - how to do the work, what to look up, what they've learned, the files you share, the work they produce, and which accounts they work with."
        title="Context"
      />

      <div className="divide-border divide-y" aria-label="Context sections">
        {contextSections.map((section) => {
          const Icon = section.icon

          return (
            <Link
              className="focus-visible:ring-ring/50 group hover:bg-muted/45 flex min-h-24 items-center gap-3 rounded-lg px-2 py-4 transition-colors outline-none focus-visible:ring-[3px] sm:gap-4 sm:px-3"
              key={section.to}
              to={section.to}
            >
              <span className="border-border bg-background flex size-10 shrink-0 items-center justify-center rounded-xl border shadow-xs">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{section.label}</span>
                <span className="mt-0.5 block text-sm">{section.description}</span>
                <span className="text-muted-foreground mt-1 block text-sm">{section.when}</span>
              </span>
              <ChevronRightIcon
                className="text-muted-foreground size-4 shrink-0 transition-transform group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            </Link>
          )
        })}
      </div>
    </div>
  )
}
