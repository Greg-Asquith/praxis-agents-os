// apps/web/src/features/agents/components/agents-table.tsx

import { useMemo } from "react"
import { Link } from "@tanstack/react-router"
import { BotIcon, MessageSquarePlusIcon, PencilIcon, PlusIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} from "@/components/data-table/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
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
import { countApprovalPolicyTools } from "@/features/agents/agent-metrics"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { AgentStatusBadges } from "@/features/agents/components/agent-status-badges"
import { formatAgentModel } from "@/features/agents/components/agent-model-label"
import type { Agent } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import { formatDateTime, pluralize } from "@/lib/format"

const columnHelper = createAppColumnHelper<Agent>()

export function AgentsTable({
  agents,
  modelCatalog,
}: {
  agents: Agent[]
  modelCatalog: ModelCatalogResponse
}) {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("name", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex min-w-56 items-start gap-2.5">
              <AgentIdentityIcon
                agentId={row.original.id}
                decorative
                metadata={row.original.metadata}
                name={row.original.name}
              />
              <div className="flex min-w-0 flex-col gap-1">
                <span className="font-medium">{row.original.name}</span>
                {row.original.description ? (
                  <span className="text-muted-foreground max-w-md truncate text-xs">
                    {row.original.description}
                  </span>
                ) : null}
              </div>
            </div>
          ),
          meta: { label: "Name" },
        }),
        columnHelper.display({
          id: "status",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => <AgentStatusBadges agent={row.original} />,
          meta: { label: "Status" },
        }),
        columnHelper.display({
          id: "model",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) =>
            formatAgentModel(row.original, modelCatalog, { showDefaultLabel: false }),
          meta: { label: "Model" },
        }),
        columnHelper.display({
          id: "tools",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <AgentToolsSummary
              approvalCount={countApprovalPolicyTools(row.original)}
              toolCount={row.original.tool_names.length}
            />
          ),
          meta: { label: "Tools" },
        }),
        columnHelper.accessor("updated_at", {
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ getValue }) => formatDateTime(getValue()),
          meta: { label: "Updated" },
        }),
        columnHelper.display({
          id: "actions",
          header: ({ header }) => <header.ColumnHeader />,
          cell: ({ row }) => (
            <div className="flex items-center justify-end gap-2">
              {row.original.is_active ? (
                <Button
                  render={<Link search={{ agent: row.original.id }} to="/conversations/new" />}
                  size="sm"
                  variant="outline"
                >
                  <MessageSquarePlusIcon data-icon="inline-start" />
                  Chat
                </Button>
              ) : null}
              <Button
                render={<Link params={{ agentId: row.original.id }} to="/agents/$agentId" />}
                size="sm"
                variant="outline"
              >
                <PencilIcon data-icon="inline-start" />
                Edit
              </Button>
            </div>
          ),
          meta: { label: "Actions", labelClassName: "sr-only" },
        }),
      ]),
    [modelCatalog]
  )
  const table = useAppTable({ columns, data: agents })

  if (agents.length === 0) {
    return (
      <EmptyState
        action={
          <Button render={<Link to="/agents/new" />}>
            <PlusIcon data-icon="inline-start" />
            New Agent
          </Button>
        }
        description="Create the first agent to start conversations in this workspace."
        icon={<BotIcon className="size-5" />}
        size="compact"
        title="No agents yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {agents.map((agent) => (
          <AgentMobileRow key={agent.id} agent={agent} modelCatalog={modelCatalog} />
        ))}
      </ResponsiveList>

      <table.AppTable>
        <AgentsDesktopTable />
      </table.AppTable>
    </div>
  )
}

function AgentsDesktopTable() {
  const table = useTableContext<Agent>()

  return (
    <div className="hidden md:block">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <table.AppHeader header={header} key={header.id}>
                  {() => <AgentHeaderCell />}
                </table.AppHeader>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <table.AppCell cell={cell} key={cell.id}>
                  {() => <AgentBodyCell />}
                </table.AppCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function AgentHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function AgentBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.id === "actions" ? "text-right" : undefined}>
      <cell.FlexRender />
    </TableCell>
  )
}

function AgentMobileRow({
  agent,
  modelCatalog,
}: {
  agent: Agent
  modelCatalog: ModelCatalogResponse
}) {
  const approvalPolicyTools = countApprovalPolicyTools(agent)

  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <AgentIdentityIcon
              agentId={agent.id}
              decorative
              metadata={agent.metadata}
              name={agent.name}
            />
            <div className="min-w-0">
              <p className="truncate font-medium">{agent.name}</p>
            </div>
          </div>
          <AgentStatusBadges agent={agent} />
        </div>

        {agent.description ? (
          <p className="text-muted-foreground line-clamp-2 text-xs leading-5">
            {agent.description}
          </p>
        ) : null}

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Model">
            {formatAgentModel(agent, modelCatalog, { showDefaultLabel: false })}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Tools">
            <AgentToolsSummary
              approvalCount={approvalPolicyTools}
              toolCount={agent.tool_names.length}
            />
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Updated">
            {formatDateTime(agent.updated_at)}
          </ResponsiveListMeta>
        </dl>

        <div className="flex gap-2">
          {agent.is_active ? (
            <Button
              className="flex-1"
              variant="outline"
              render={<Link to="/conversations/new" search={{ agent: agent.id }} />}
            >
              <MessageSquarePlusIcon data-icon="inline-start" />
              Chat
            </Button>
          ) : null}
          <Button
            className="flex-1"
            variant="outline"
            render={<Link to="/agents/$agentId" params={{ agentId: agent.id }} />}
          >
            <PencilIcon data-icon="inline-start" />
            Edit
          </Button>
        </div>
      </div>
    </ResponsiveListItem>
  )
}

function AgentToolsSummary({
  approvalCount,
  toolCount,
}: {
  approvalCount: number
  toolCount: number
}) {
  if (toolCount === 0) {
    return <span className="text-muted-foreground text-sm">No tools</span>
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline">
        {toolCount} {pluralize(toolCount, "tool")}
      </Badge>
      {approvalCount > 0 ? (
        <Badge variant="secondary">
          {approvalCount} {approvalCount === 1 ? "needs" : "need"} approval
        </Badge>
      ) : null}
    </div>
  )
}
