// apps/web/src/integrations/contract.ts

import type { ComponentType, ReactNode, SVGProps } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { IntegrationProvider } from "@/features/integrations/types"
import type { ToolUi } from "@/features/tools/types"

export type { ToolActivity } from "@/features/conversations/message-parts"
export type { ToolUi } from "@/features/tools/types"

export type ToolRowPresenterProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
  label?: string
  live: boolean
  providerKey: string | null
  ui?: ToolUi | null
}

export type ToolRowPresenter = {
  /** Opts into replacing the default approve/decline UI for pending tool calls. */
  handlesApprovals?: boolean
  key: string
  matches: (activity: ToolActivity) => boolean
  render: (props: ToolRowPresenterProps) => ReactNode
}

export type IntegrationUiModule = {
  catalogDescription?: string
  providerKey: string
  toolRowPresenters?: ToolRowPresenter[]
  icons?: Record<string, ComponentType<SVGProps<SVGSVGElement>>>
  ConnectHelp?: ComponentType<{ provider: IntegrationProvider }>
}
