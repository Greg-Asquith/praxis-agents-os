// apps/web/src/features/conversations/components/code-mode-row.tsx

import { use, useEffect, useMemo, useRef, useState } from "react"
import { Workflow } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ToolCallRowRendererContext } from "@/features/conversations/components/tool-call-row-renderer"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize } from "@/lib/format"

const COLLAPSED_CHILD_LIMIT = 12

export function CodeModeRow({
  activity,
  defaultOpen = false,
  live = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
  live?: boolean
}) {
  const script = activity.script
  const [showAll, setShowAll] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const renderToolCallRow = use(ToolCallRowRendererContext)
  const pendingChild = script?.children.find((child) => child.status === "awaiting_approval")
  const pendingChildId = pendingChild?.id ?? null
  const visibleChildren = useMemo(() => {
    if (!script) {
      return []
    }
    if (showAll || script.children.length <= COLLAPSED_CHILD_LIMIT) {
      return script.children
    }
    const initial = script.children.slice(0, COLLAPSED_CHILD_LIMIT)
    return pendingChild && !initial.includes(pendingChild) ? [...initial, pendingChild] : initial
  }, [pendingChild, script, showAll])

  useEffect(() => {
    if (!pendingChildId) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      const approval = contentRef.current?.querySelector<HTMLElement>(
        'section[aria-label^="Approval request:"]'
      )
      if (!approval) {
        return
      }
      approval.tabIndex = -1
      approval.focus({ preventScroll: true })
      approval.scrollIntoView({ block: "nearest" })
    })
    return () => {
      window.cancelAnimationFrame(frame)
    }
  }, [pendingChildId])

  if (!script) {
    return null
  }
  const childCount = script.children.length
  const reason = script.reason ?? workflowStatusSummary(activity, childCount, Boolean(pendingChild))
  const modelResult =
    activity.status === "completed" && activity.result !== undefined
      ? formatWorkflowModelResult(activity.result)
      : null
  if (activity.status === "running") {
    return (
      <FanOutSkeleton heading={<CodeModeHeading />} label="Running workflow…" summary={reason} />
    )
  }

  const hiddenCount = Math.max(0, childCount - visibleChildren.length)
  return (
    <ToolResultCard
      ariaLabel={pendingChild ? "Workflow review needed" : workflowAriaLabel(activity, childCount)}
      defaultOpen={defaultOpen || Boolean(pendingChild)}
      details={[{ label: "Summary", value: reason }]}
      heading={<CodeModeHeading />}
      key={pendingChildId ?? `settled:${activity.status}`}
      trailing={<WorkflowStatus activity={activity} pending={Boolean(pendingChild)} />}
    >
      <div className="flex min-w-0 flex-col gap-3" ref={contentRef}>
        {script.reason ? <p className="text-muted-foreground text-sm">{script.reason}</p> : null}
        {visibleChildren.length > 0 ? (
          <ol aria-label="Workflow tool calls" className="flex min-w-0 flex-col gap-2">
            {visibleChildren.map((child) => (
              <li
                className="[contain-intrinsic-size:auto_3rem] [content-visibility:auto]"
                key={child.id}
              >
                {renderToolCallRow?.({ activity: child, compact: true, live })}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground text-sm">No tool calls were recorded.</p>
        )}
        {!showAll && hiddenCount > 0 ? (
          <Button
            className="self-start"
            onClick={() => {
              setShowAll(true)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Show all {String(childCount)} tool calls
          </Button>
        ) : null}
        {script.code ? (
          <details className="group/script min-w-0">
            <summary className="text-muted-foreground hover:text-foreground w-fit cursor-pointer text-xs font-medium">
              Show script
            </summary>
            <pre className="bg-muted/50 mt-2 max-h-72 overflow-auto rounded-md p-3 font-mono text-xs wrap-break-word whitespace-pre-wrap">
              <code>{script.code}</code>
            </pre>
          </details>
        ) : null}
        {modelResult !== null ? (
          <details className="group/model-result min-w-0">
            <summary className="text-muted-foreground hover:text-foreground w-fit cursor-pointer text-xs font-medium">
              Show output sent to model
            </summary>
            <pre className="bg-muted/50 mt-2 max-h-72 overflow-auto rounded-md p-3 font-mono text-xs wrap-break-word whitespace-pre-wrap">
              <code>{modelResult}</code>
            </pre>
          </details>
        ) : null}
        {script.error ? <p className="text-destructive text-sm">{script.error}</p> : null}
      </div>
    </ToolResultCard>
  )
}

function formatWorkflowModelResult(value: unknown): string {
  if (typeof value === "string") {
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function CodeModeHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Workflow className="text-muted-foreground size-4 shrink-0" />
      <span>Workflow</span>
    </span>
  )
}

function WorkflowStatus({ activity, pending }: { activity: ToolActivity; pending: boolean }) {
  if (pending) {
    return <Badge variant="warning">Review needed</Badge>
  }
  if (activity.status === "failed") {
    return <Badge variant="destructive">Couldn’t finish</Badge>
  }
  // An answered approval keeps the outer call in awaiting_approval until the
  // resumed run status lands, so it reads as working, never done.
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    return <Badge variant="secondary">Working</Badge>
  }
  return <Badge variant="success">Done</Badge>
}

function workflowStatusSummary(activity: ToolActivity, childCount: number, pending = false) {
  if (pending) {
    return "Waiting for your review"
  }
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    return childCount === 0
      ? "Preparing workflow"
      : `Using ${String(childCount)} ${pluralize(childCount, "tool call")}…`
  }
  if (activity.status === "failed") {
    return childCount === 0
      ? "The workflow could not finish"
      : `Stopped after ${String(childCount)} ${pluralize(childCount, "tool call")}`
  }
  return `Completed with ${String(childCount)} ${pluralize(childCount, "tool call")}`
}

function workflowAriaLabel(activity: ToolActivity, childCount: number) {
  return activity.status === "failed"
    ? `Workflow stopped after ${String(childCount)} ${pluralize(childCount, "tool call")}`
    : `Workflow with ${String(childCount)} ${pluralize(childCount, "tool call")}`
}
