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
    description: "Teach your agents how you like a job done, so they do it your way every time.",
    when: "Use it for repeatable work - like producing the weekly report in exactly your format.",
  },
  {
    label: "Knowledge Base",
    to: "/knowledge",
    icon: LibraryIcon,
    description:
      "A library of documents your agents check before answering, so they get the facts right.",
    when: "Use it for information that must be accurate - your policies, product details, and pricing.",
  },
  {
    label: "Memory",
    to: "/memories",
    icon: BrainIcon,
    description:
      "Things your agents have learned about you and your work, so you never have to repeat yourself.",
    when: "Come here to see what they've remembered, fix anything wrong, and clear out anything out of date.",
  },
  {
    label: "Files",
    to: "/files",
    icon: FilesIcon,
    description: "Documents and spreadsheets you upload for your agents to work with.",
    when: "Use it to hand an agent the materials for a job - like a spreadsheet to tidy up or a brief to write from.",
  },
  {
    label: "Artifacts",
    to: "/artifacts",
    icon: FileStackIcon,
    description:
      "The finished work your agents produce, with every earlier version kept safe so nothing is lost.",
    when: "Come here to open, share, or go back to an earlier version of anything an agent has made.",
  },
  {
    label: "Context Groups",
    to: "/integrations/context-groups",
    icon: Layers3Icon,
    description:
      "Bundles of accounts and resources you name once, so an agent always knows which ones to use.",
    when: "Use it when different agents should work with different accounts - like one agent for each client.",
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
              <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-lg">
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{section.label}</span>
                <span className="text-muted-foreground mt-0.5 block text-sm">
                  {section.description}
                </span>
                <span className="text-muted-foreground mt-1 block text-xs">{section.when}</span>
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
