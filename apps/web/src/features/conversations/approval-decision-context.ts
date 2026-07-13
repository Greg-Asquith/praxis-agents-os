// apps/web/src/features/conversations/approval-decision-context.ts

import { createContext } from "react"

import type { ToolApprovalDecisionControls } from "@/features/conversations/components/approval-decision-block"
import type { ToolActivity } from "@/features/conversations/message-parts"

export type ApprovalDecisionResolver = (
  activity: ToolActivity
) => ToolApprovalDecisionControls | null

// Tool rows resolve inline approval controls through this context so pending
// decisions render in the same transcript slot as the tool call itself.
export const ApprovalDecisionContext = createContext<ApprovalDecisionResolver>(() => null)
