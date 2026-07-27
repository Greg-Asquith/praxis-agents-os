// apps/web/src/features/memories/components/supersession-chain.tsx

import { useId, useState } from "react"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { Memory } from "@/features/memories/types"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

export function SupersessionChain({
  chain,
  currentId,
  onSelect,
}: {
  chain: Memory[]
  currentId: string
  onSelect: (memoryId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const historyId = useId()

  if (chain.length <= 1) {
    return null
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-heading font-medium">Version History</h3>
          <p className="text-muted-foreground text-sm">{chain.length} saved versions</p>
        </div>
        <Button
          aria-controls={historyId}
          aria-expanded={open}
          onClick={() => {
            setOpen((current) => !current)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          {open ? "Hide Versions" : `Show ${String(chain.length)} Versions`}
          {open ? (
            <ChevronUpIcon data-icon="inline-end" />
          ) : (
            <ChevronDownIcon data-icon="inline-end" />
          )}
        </Button>
      </div>
      {open ? (
        <ol className="border-border flex flex-col border-l" id={historyId}>
          {chain.map((memory, index) => (
            <li
              className={cn(
                "relative ml-4 rounded-lg p-3",
                memory.id === currentId ? "bg-muted" : "text-muted-foreground"
              )}
              key={memory.id}
            >
              <span className="bg-border absolute top-5 -left-[1.2rem] size-2 rounded-full" />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  className="h-auto p-0 font-medium"
                  onClick={() => {
                    onSelect(memory.id)
                  }}
                  type="button"
                  variant="link"
                >
                  Version {index + 1}
                </Button>
                {memory.id === currentId ? <Badge variant="secondary">Selected</Badge> : null}
                <span className="text-xs">{formatDateTime(memory.updated_at)}</span>
              </div>
              <p className="mt-2 line-clamp-3 text-sm whitespace-pre-wrap">{memory.content_md}</p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  )
}
