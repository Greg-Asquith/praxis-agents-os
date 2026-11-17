// apps/web/src/features/conversations/components/delegation-tool-presenter.tsx

import {
  DelegateAgentListRow,
  DelegationToolRow,
} from "@/features/conversations/components/delegation-tool-row"
import {
  LIST_DELEGATE_AGENTS_TOOL_NAME,
  delegateAgentSummaries,
} from "@/features/conversations/delegation-agent-list"
import type { ToolRowPresenter } from "@/integrations/contract"

export const delegationToolPresenters: ToolRowPresenter[] = [
  {
    key: "delegate-agent-list",
    matches: (activity) =>
      activity.name === LIST_DELEGATE_AGENTS_TOOL_NAME &&
      (activity.status === "running" || delegateAgentSummaries(activity.result) !== null),
    render: ({ activity, defaultOpen }) => (
      <DelegateAgentListRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    handlesApprovals: true,
    key: "delegation",
    matches: (activity) => Boolean(activity.delegate),
    render: ({ activity, approvalDecision, defaultOpen }) => (
      <DelegationToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        defaultOpen={defaultOpen}
      />
    ),
  },
]
