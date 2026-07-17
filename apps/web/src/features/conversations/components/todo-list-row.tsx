// apps/web/src/features/conversations/components/todo-list-row.tsx

import { CheckCircle2Icon, CircleDotIcon, CircleIcon, ListTodoIcon } from "lucide-react"

import { ToolField } from "@/features/conversations/components/tool-field"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import { toolStatusSuffix } from "@/features/conversations/components/tool-activity-status-values"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  type TodoToolItem,
  WRITE_TODOS_TOOL_NAME,
  todoItemsFromActivity,
} from "@/features/conversations/todo-tools"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type TodoListRowProps = {
  activity: ToolActivity
  compact: boolean
}

export function TodoListRow({ activity, compact }: TodoListRowProps) {
  const items = todoItemsFromActivity(activity)
  if (!items) {
    return null
  }
  const keyedItems = withStableKeys(items)
  const expandable = items.length > 0

  const header = (
    <ToolActivityRowHeader
      expandable={expandable}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <ListTodoIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">{todoHeadline(activity, items)}</span>
        </span>
      }
      suffix={
        <ActivityStatusSuffix status={activity.status} suffix={todoSuffix(activity, items)} />
      }
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={expandable}
      expandable={expandable}
      header={header}
    >
      {items.length > 0 ? (
        <ToolField
          field={{
            key: "plan",
            label: `Plan · ${String(items.length)} ${pluralize(items.length, "item")}`,
            value: "",
            format: "text",
          }}
        >
          <ul className="flex min-w-0 flex-col gap-1">
            {keyedItems.map((item) => (
              <li
                key={item.key}
                className="flex min-w-0 items-start gap-1.5 text-xs leading-relaxed"
              >
                <TodoItemIcon status={item.status} />
                <span
                  className={cn(
                    "min-w-0",
                    item.status === "completed" && "text-muted-foreground line-through",
                    item.status === "in_progress" && "text-foreground font-medium",
                    item.status === "pending" && "text-muted-foreground"
                  )}
                >
                  {item.content}
                </span>
              </li>
            ))}
          </ul>
        </ToolField>
      ) : null}
    </ToolActivityRowShell>
  )
}

function withStableKeys(items: TodoToolItem[]) {
  const seen = new Map<string, number>()
  return items.map((item) => {
    const base = `${item.status}:${item.content}`
    const count = seen.get(base) ?? 0
    seen.set(base, count + 1)
    return { ...item, key: count > 0 ? `${base}:${String(count)}` : base }
  })
}

function TodoItemIcon({ status }: { status: TodoToolItem["status"] }) {
  if (status === "completed") {
    return <CheckCircle2Icon className="text-success mt-0.5 size-3.5 shrink-0" />
  }
  if (status === "in_progress") {
    return <CircleDotIcon className="text-primary mt-0.5 size-3.5 shrink-0" />
  }
  return <CircleIcon className="text-muted-foreground/60 mt-0.5 size-3.5 shrink-0" />
}

function todoHeadline(activity: ToolActivity, items: TodoToolItem[]) {
  const isWrite = activity.name === WRITE_TODOS_TOOL_NAME
  if (activity.status === "running") {
    return isWrite ? "Updating the Plan" : "Checking the Plan"
  }
  if (activity.status === "failed") {
    return isWrite ? "Couldn't Update the Plan" : "Couldn't Read the Plan"
  }
  if (items.length === 0) {
    return isWrite ? "Cleared the Plan" : "No Plan Yet"
  }
  return "Plan"
}

function todoSuffix(activity: ToolActivity, items: TodoToolItem[]) {
  const statusSuffix = toolStatusSuffix(activity)
  if (statusSuffix) {
    return statusSuffix
  }
  if (items.length === 0) {
    return null
  }
  const done = items.filter((item) => item.status === "completed").length
  return `${String(done)} of ${String(items.length)} done`
}
