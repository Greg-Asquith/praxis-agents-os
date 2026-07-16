// apps/web/src/features/agents/components/agents-table.tsx

import { Link } from "@tanstack/react-router"
import { BotIcon, PencilIcon, PlusIcon } from "lucide-react"

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

export function AgentsTable({
  agents,
  modelCatalog,
}: {
  agents: Agent[]
  modelCatalog: ModelCatalogResponse
}) {
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

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Tools</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.map((agent) => {
              const approvalPolicyTools = countApprovalPolicyTools(agent)

              return (
                <TableRow key={agent.id}>
                  <TableCell>
                    <div className="flex min-w-56 items-start gap-2.5">
                      <AgentIdentityIcon agentId={agent.id} decorative name={agent.name} />
                      <div className="flex min-w-0 flex-col gap-1">
                        <span className="font-medium">{agent.name}</span>
                        {agent.description && (
                          <span className="text-muted-foreground max-w-md truncate text-xs">
                            {agent.description}
                          </span>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <AgentStatusBadges agent={agent} />
                  </TableCell>
                  <TableCell>{formatAgentModel(agent, modelCatalog)}</TableCell>
                  <TableCell>
                    <AgentToolsSummary
                      approvalCount={approvalPolicyTools}
                      toolCount={agent.tool_names.length}
                    />
                  </TableCell>
                  <TableCell>{formatDateTime(agent.updated_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      render={<Link to="/agents/$agentId" params={{ agentId: agent.id }} />}
                    >
                      <PencilIcon data-icon="inline-start" />
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
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
            <AgentIdentityIcon agentId={agent.id} decorative name={agent.name} />
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
            {formatAgentModel(agent, modelCatalog)}
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

        <Button
          className="w-full"
          variant="outline"
          render={<Link to="/agents/$agentId" params={{ agentId: agent.id }} />}
        >
          <PencilIcon data-icon="inline-start" />
          Edit
        </Button>
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
