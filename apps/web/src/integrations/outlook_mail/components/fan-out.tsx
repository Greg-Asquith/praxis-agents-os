// apps/web/src/integrations/outlook_mail/components/fan-out.tsx

import type { ReactNode } from "react"

import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton, type FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { OutlookToolHeading } from "@/integrations/outlook_mail/components/tool-heading"

const NO_DETAILS: FanOutDetail[] = []

// Mailbox identifiers are opaque Graph IDs, so cards show only the mailbox name.
export function OutlookFanOut({
  children,
  defaultOpen,
  details,
  emptyLabel,
  entries,
  title,
}: {
  children: (entry: FanOutEntry, index: number) => ReactNode
  defaultOpen: boolean
  details?: FanOutDetail[] | undefined
  emptyLabel: string
  entries: FanOutEntry[]
  title: string
}) {
  return (
    <div aria-label={`${title} results`} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Mailbox"
        defaultOpen={defaultOpen}
        details={details ?? NO_DETAILS}
        entries={entries}
        emptyLabel={emptyLabel}
        externalLabel={null}
        heading={<OutlookToolHeading>{title}</OutlookToolHeading>}
      >
        {children}
      </FanOutShell>
    </div>
  )
}

export function OutlookSkeleton({ label, title }: { label: string; title: string }) {
  return <FanOutSkeleton heading={<OutlookToolHeading>{title}</OutlookToolHeading>} label={label} />
}
