// apps/web/src/features/conversations/components/tool-call-row-renderer.ts

import { createContext, type ReactNode } from "react"

import type { ToolActivity } from "@/features/conversations/message-parts"

export type ToolCallRowRenderProps = {
  activity: ToolActivity
  compact?: boolean
  defaultOpen?: boolean
  live?: boolean
}

export type ToolCallRowRenderer = (props: ToolCallRowRenderProps) => ReactNode

export const ToolCallRowRendererContext = createContext<ToolCallRowRenderer | null>(null)
