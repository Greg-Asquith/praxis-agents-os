// apps/web/src/features/agents/components/agents-table.tsx

import { Link } from "@tanstack/react-router"
import { Settings2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { countApprovalPolicyTools } from "@/features/agents/agent-metrics"
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
      <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center">
        <h2 className="font-heading text-lg font-semibold">No agents yet</h2>
        <p className="text-muted-foreground mt-2 max-w-md text-sm">
          Create the first workspace agent to start conversations and configure approval policies.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Runtime</TableHead>
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
                  <div className="flex min-w-56 flex-col gap-1">
                    <span className="font-medium">{agent.name}</span>
                    <span className="text-muted-foreground text-xs">{agent.slug}</span>
                    {agent.description && (
                      <span className="text-muted-foreground max-w-md truncate text-xs">
                        {agent.description}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <AgentStatusBadges agent={agent} />
                </TableCell>
                <TableCell>{formatAgentModel(agent, modelCatalog)}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline">
                      {agent.tool_names.length} {pluralize(agent.tool_names.length, "tool")}
                    </Badge>
                    {approvalPolicyTools > 0 && (
                      <Badge variant="secondary">
                        {approvalPolicyTools} approval {pluralize(approvalPolicyTools, "gate")}
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell>{formatDateTime(agent.updated_at)}</TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    render={<Link to="/agents/$agentId" params={{ agentId: agent.id }} />}
                  >
                    <Settings2Icon data-icon="inline-start" />
                    Configure
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
