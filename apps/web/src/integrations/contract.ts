// apps/web/src/integrations/contract.ts

import type { ComponentType, ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import type { ToolApprovalDecisionControls } from "@/features/conversations/components/approval-decision-block"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { IntegrationProvider } from "@/features/integrations/types"

export type { ToolActivity } from "@/features/conversations/message-parts"
export type { ToolUi } from "@/features/tools/types"

export type ToolRowPresenterProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
  live: boolean
  providerKey: string | null
}

export type ToolRowPresenter = {
  key: string
  matches: (activity: ToolActivity) => boolean
  render: (props: ToolRowPresenterProps) => ReactNode
}

export type IntegrationUiModule = {
  providerKey: string
  toolRowPresenters?: ToolRowPresenter[]
  icons?: Record<string, LucideIcon>
  ConnectHelp?: ComponentType<{ provider: IntegrationProvider }>
}
