// apps/web/src/features/memories/components/memories-table.tsx

import { BrainIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { PaginationControls } from "@/components/ui/pagination-controls"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  formatMemoryConfidence,
  memoryScopeLabel,
} from "@/features/memories/components/memory-display"
import type { Memory } from "@/features/memories/types"
import { relativeDateTime, titleCaseToken } from "@/lib/format"

export function MemoriesTable({
  limit,
  memories,
  offset,
  onOpen,
  onPageChange,
  total,
}: {
  limit: number
  memories: Memory[]
  offset: number
  onOpen: (memoryId: string) => void
  onPageChange: (offset: number) => void
  total: number
}) {
  if (memories.length === 0) {
    return (
      <EmptyState
        description="Agents save durable details here as they work. Notes stay searchable, while core memories are available on every relevant run."
        icon={<BrainIcon className="size-5" />}
        size="compact"
        title="No memories match these filters"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {memories.map((memory) => (
          <ResponsiveListItem key={memory.id}>
            <button
              className="flex w-full flex-col gap-3 text-left"
              onClick={() => {
                onOpen(memory.id)
              }}
              type="button"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium">{memory.title}</span>
                <KindBadge kind={memory.kind} />
              </div>
              <dl className="grid grid-cols-2 gap-3">
                <ResponsiveListMeta label="Scope">{memoryScopeLabel(memory)}</ResponsiveListMeta>
                <ResponsiveListMeta label="Type">
                  {titleCaseToken(memory.memory_type, "Memory")}
                </ResponsiveListMeta>
                <ResponsiveListMeta label="Confidence">
                  {formatMemoryConfidence(memory.effective_confidence)}
                </ResponsiveListMeta>
                <ResponsiveListMeta label="Updated">
                  {relativeDateTime(memory.updated_at)}
                </ResponsiveListMeta>
              </dl>
            </button>
          </ResponsiveListItem>
        ))}
      </ResponsiveList>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {memories.map((memory) => (
              <TableRow key={memory.id}>
                <TableCell>
                  <Button
                    className="h-auto max-w-sm justify-start truncate p-0 font-medium"
                    onClick={() => {
                      onOpen(memory.id)
                    }}
                    type="button"
                    variant="link"
                  >
                    {memory.title}
                  </Button>
                </TableCell>
                <TableCell>
                  <ScopeBadge scope={memory.scope} />
                </TableCell>
                <TableCell>
                  <KindBadge kind={memory.kind} />
                </TableCell>
                <TableCell>{titleCaseToken(memory.memory_type, "Memory")}</TableCell>
                <TableCell>{memory.agent_name ?? "—"}</TableCell>
                <TableCell>{formatMemoryConfidence(memory.effective_confidence)}</TableCell>
                <TableCell title={memory.updated_at}>
                  {relativeDateTime(memory.updated_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PaginationControls limit={limit} offset={offset} onPageChange={onPageChange} total={total} />
    </div>
  )
}

function KindBadge({ kind }: { kind: Memory["kind"] }) {
  return (
    <Badge variant={kind === "core" ? "warning" : "secondary"}>
      {titleCaseToken(kind, "Memory")}
    </Badge>
  )
}

function ScopeBadge({ scope }: { scope: Memory["scope"] }) {
  return (
    <Badge variant="outline">
      {scope === "user" ? "Personal" : titleCaseToken(scope, "Scope")}
    </Badge>
  )
}
