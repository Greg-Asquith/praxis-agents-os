// apps/web/src/features/home/components/attention-queue.tsx

import { useMemo, useState } from "react"
import { Link } from "@tanstack/react-router"
import {
  CheckIcon,
  CircleAlertIcon,
  CircleIcon,
  Clock3Icon,
  MessageSquareTextIcon,
  ShieldAlertIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { usePendingApprovalsQuery } from "@/features/conversations/api/list-pending-approvals"
import type { Conversation } from "@/features/conversations/types"
import { HomeSection } from "@/features/home/components/home-section"
import { buildAttentionItems, type AttentionItem } from "@/features/home/attention-items"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"
import { relativeDateTime } from "@/lib/format"

const VISIBLE_LIMIT = 8

type AttentionFilter = "all" | AttentionItem["kind"]

export function AttentionQueue({ conversations }: { conversations: Conversation[] }) {
  const { data: approvals } = usePendingApprovalsQuery()
  const { data: schedulesData } = useSchedulesQuery({ includeInactive: true, limit: 100 })
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const [filter, setFilter] = useState<AttentionFilter>("all")
  const [expanded, setExpanded] = useState(false)
  const agentsById = useMemo(
    () => new Map(agentsData.agents.map((agent) => [agent.id, agent])),
    [agentsData.agents]
  )
  const items = useMemo(
    () =>
      buildAttentionItems({
        approvals,
        schedules: schedulesData.items,
        conversations,
        agentsById,
      }),
    [agentsById, approvals, conversations, schedulesData.items]
  )
  const counts = countItems(items, approvals.total)
  const availableKinds = (["approval", "schedule", "unread"] as const).filter(
    (kind) => counts[kind] > 0
  )

  if (items.length === 0 && approvals.total === 0) {
    return (
      <div className="flex items-center gap-2 px-2 py-3 text-sm">
        <CheckIcon aria-hidden="true" className="text-success size-4 shrink-0" />
        <span>Nothing needs your attention</span>
        <span className="text-muted-foreground">
          Schedules are healthy and every conversation is read
        </span>
      </div>
    )
  }

  const effectiveFilter = filter !== "all" && counts[filter] === 0 ? "all" : filter
  const filteredItems =
    effectiveFilter === "all" ? items : items.filter((item) => item.kind === effectiveFilter)
  const visibleItems = expanded ? filteredItems : filteredItems.slice(0, VISIBLE_LIMIT)
  const filteredTotal = effectiveFilter === "all" ? counts.all : counts[effectiveFilter]
  const hiddenCount = Math.max(0, filteredTotal - visibleItems.length)
  const canExpand = !expanded && filteredItems.length > VISIBLE_LIMIT
  const unavailableApprovals = Math.max(0, approvals.total - approvals.items.length)
  const showUnavailableApprovals =
    unavailableApprovals > 0 &&
    (expanded || filteredItems.length <= VISIBLE_LIMIT) &&
    (effectiveFilter === "all" || effectiveFilter === "approval")

  return (
    <HomeSection
      action={
        availableKinds.length > 1 ? (
          <Tabs
            value={effectiveFilter}
            onValueChange={(value) => {
              if (isAttentionFilter(value)) {
                setFilter(value)
                setExpanded(false)
              }
            }}
          >
            <TabsList aria-label="Filter attention items">
              <CountTab label="All" count={counts.all} value="all" />
              {counts.approval > 0 ? (
                <CountTab label="Approvals" count={counts.approval} value="approval" />
              ) : null}
              {counts.schedule > 0 ? (
                <CountTab label="Schedules" count={counts.schedule} value="schedule" />
              ) : null}
              {counts.unread > 0 ? (
                <CountTab label="Unread" count={counts.unread} value="unread" />
              ) : null}
            </TabsList>
          </Tabs>
        ) : null
      }
      description="Approvals first, then failing schedules, then results you haven't read."
      title="Needs your attention"
    >
      <div className="flex flex-col gap-1">
        {visibleItems.map((item) => (
          <AttentionRow
            agentsById={agentsById}
            item={item}
            key={`${item.kind}-${item.id}`}
            latestConversationId={
              item.kind === "schedule"
                ? (schedulesData.items.find((schedule) => schedule.id === item.scheduleId)
                    ?.latest_run?.conversation_id ?? null)
                : null
            }
          />
        ))}
        {canExpand ? (
          <Button
            className="self-start"
            size="sm"
            variant="link"
            onClick={() => {
              setExpanded(true)
            }}
          >
            Show {String(hiddenCount)} more
          </Button>
        ) : null}
        {showUnavailableApprovals ? (
          <p className="text-muted-foreground px-3 pt-2 pb-1 text-xs">
            and {String(unavailableApprovals)} more
          </p>
        ) : null}
      </div>
    </HomeSection>
  )
}

function AttentionRow({
  agentsById,
  item,
  latestConversationId,
}: {
  agentsById: Map<string, { metadata: Record<string, unknown> | null }>
  item: AttentionItem
  latestConversationId: string | null
}) {
  const content = (
    <>
      <AgentIdentityIcon
        agentId={item.agentId ?? item.id}
        decorative
        metadata={item.agentId ? agentsById.get(item.agentId)?.metadata : null}
        name={item.agentName}
        size="md"
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{item.title}</span>
        <span
          className={`line-clamp-1 text-xs ${item.kind === "schedule" && item.errorMessage ? "text-destructive" : "text-muted-foreground"}`}
        >
          {item.kind === "schedule" && item.errorMessage
            ? `${item.agentName} · ${item.errorMessage}`
            : item.subtitle}
        </span>
      </span>
      <AttentionBadge item={item} />
      {item.at ? (
        <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
          <Clock3Icon aria-hidden="true" className="size-3" />
          {relativeDateTime(item.at)}
        </span>
      ) : null}
    </>
  )

  return (
    <div className="hover:bg-muted flex min-w-0 items-center gap-3 rounded-lg px-3 py-2.5 transition-colors">
      <Link
        className="focus-visible:ring-ring -m-1 flex min-w-0 flex-1 items-center gap-3 rounded-md p-1 focus-visible:ring-2 focus-visible:outline-none"
        params={
          item.kind === "schedule"
            ? { scheduleId: item.scheduleId }
            : { conversationId: item.conversationId }
        }
        to={item.kind === "schedule" ? "/schedules/$scheduleId" : "/conversations/$conversationId"}
      >
        {content}
      </Link>
      {item.kind === "schedule" && latestConversationId ? (
        <Button
          aria-label={`Open latest run for ${item.title}`}
          size="icon-sm"
          variant="ghost"
          render={
            <Link
              params={{ conversationId: latestConversationId }}
              to="/conversations/$conversationId"
            />
          }
        >
          <MessageSquareTextIcon />
        </Button>
      ) : null}
    </div>
  )
}

function AttentionBadge({ item }: { item: AttentionItem }) {
  if (item.kind === "approval") {
    return (
      <Badge variant="warning">
        <ShieldAlertIcon data-icon="inline-start" />
        Approve
      </Badge>
    )
  }
  if (item.kind === "schedule") {
    return item.health === "needs_attention" ? (
      <Badge variant="destructive">
        <CircleAlertIcon data-icon="inline-start" />
        Schedule failing
      </Badge>
    ) : (
      <Badge variant="warning">Retrying</Badge>
    )
  }
  return (
    <Badge variant="outline">
      <CircleIcon className="fill-current" data-icon="inline-start" />
      Unread
    </Badge>
  )
}

function CountTab({
  count,
  label,
  value,
}: {
  count: number
  label: string
  value: AttentionFilter
}) {
  return (
    <TabsTrigger value={value}>
      {label} <span className="tabular-nums">{String(count)}</span>
    </TabsTrigger>
  )
}

function countItems(items: AttentionItem[], approvalTotal: number) {
  const counts = { approval: approvalTotal, schedule: 0, unread: 0 }
  for (const item of items) {
    if (item.kind !== "approval") {
      counts[item.kind] += 1
    }
  }
  return { ...counts, all: counts.approval + counts.schedule + counts.unread }
}

function isAttentionFilter(value: unknown): value is AttentionFilter {
  return value === "all" || value === "approval" || value === "schedule" || value === "unread"
}
