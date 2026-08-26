// apps/web/sec/routes/home.tsx

import { useMemo } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"

import { PageHeader } from "@/components/shell/page-header"
import { agentsQueryOptions, useAgentsQuery } from "@/features/agents/api/list-agents"
import {
  conversationsQueryOptions,
  useConversationsQuery,
} from "@/features/conversations/api/list-conversations"
import { pendingApprovalsQueryOptions } from "@/features/conversations/api/list-pending-approvals"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import {
  ConversationStartingNotice,
  NoActiveAgentsAlert,
} from "@/features/conversations/components/conversation-starting-notice"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { sortConversations } from "@/features/conversations/sort"
import { AttentionQueue } from "@/features/home/components/attention-queue"
import { RecentConversations } from "@/features/home/components/recent-conversations"
import {
  modelCatalogQueryOptions,
  useModelCatalogQuery,
} from "@/features/models/api/list-model-catalog"
import { schedulesQueryOptions } from "@/features/schedules/api/list-schedules"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function HomeRoute() {
  const { workspace } = useActiveWorkspace()
  useSuspenseQueries({
    queries: [
      conversationsQueryOptions({ limit: 100 }),
      pendingApprovalsQueryOptions(),
      schedulesQueryOptions({ includeInactive: true, limit: 100 }),
      agentsQueryOptions({ includeInactive: false, limit: 100 }),
      agentsQueryOptions({ includeInactive: true, limit: 100 }),
      modelCatalogQueryOptions(),
    ],
  })
  const { data: agentsData } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const { stream } = useConversationWorkspace()
  const conversationsQuery = useConversationsQuery({ limit: 100 })
  const conversations = useMemo(
    () => sortConversations(conversationsQuery.data.conversations),
    [conversationsQuery.data.conversations]
  )
  const activeAgents = agentsData.agents.filter((agent) => agent.is_active)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader description={workspace.name} title="Home" />

      {activeAgents.length === 0 ? (
        <NoActiveAgentsAlert />
      ) : (
        <div className="flex flex-col gap-3">
          {stream.isStreaming ? <ConversationStartingNotice /> : null}
          <ConversationComposer
            agents={agentsData.agents}
            mode="create"
            modelCatalog={modelCatalog}
            showDisclaimer={false}
          />
        </div>
      )}

      <div className="divide-border flex min-w-0 flex-col divide-y *:py-7 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
        <AttentionQueue conversations={conversations} />
        <RecentConversations conversations={conversations} />
      </div>
    </div>
  )
}
