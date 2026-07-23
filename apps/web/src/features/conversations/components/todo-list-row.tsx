// apps/web/src/features/conversations/components/todo-list-row.tsx

import { CheckCircle2Icon, CircleDotIcon, CircleIcon, ListTodoIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import { toolStatusSuffix } from "@/features/conversations/components/tool-activity-status-values"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  READ_TODOS_TOOL_NAME,
  type TodoToolItem,
  todoItemsFromActivity,
} from "@/features/conversations/native-tools/todo-tools"
import { cn } from "@/lib/utils"

type TodoListRowProps = {
  activity: ToolActivity
}

export function TodoListRow({ activity }: TodoListRowProps) {
  const items = todoItemsFromActivity(activity)
  if (activity.name === READ_TODOS_TOOL_NAME && activity.status !== "completed") {
    return <PlanLookupRow activity={activity} items={items ?? []} />
  }
  if (!items) {
    return null
  }
  if (activity.name === READ_TODOS_TOOL_NAME) {
    return <PlanLookupRow activity={activity} items={items} />
  }

  const keyedItems = withStableKeys(items)
  const completedCount = countCompleted(items)
  const progress = items.length === 0 ? 0 : (completedCount / items.length) * 100
  const progressLabel = completedLabel(completedCount, items.length)

  return (
    <Card
      aria-label={`Plan, ${progressLabel}`}
      className="w-full min-w-0"
      data-slot="plan-card"
      size="sm"
    >
      <CardHeader>
        <CardTitle className="flex min-w-0 items-center gap-2">
          <span className="bg-accent text-accent-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
            <ListTodoIcon className="size-4" />
          </span>
          <span className="truncate">Plan</span>
        </CardTitle>
        <CardDescription>{planDescription(activity, items)}</CardDescription>
        <CardAction className="flex flex-col items-end gap-1">
          <PlanUpdateBadge activity={activity} />
          <span className="text-muted-foreground text-xs font-medium tabular-nums">
            {progressLabel}
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        <Progress aria-label={progressLabel} value={progress} />
        {items.length > 0 ? (
          <ul aria-label="Plan steps" className="flex min-w-0 flex-col gap-1.5">
            {keyedItems.map((item) => (
              <li
                key={item.key}
                className={cn(
                  "flex min-w-0 items-start gap-2 rounded-md px-2.5 py-2 text-sm leading-snug",
                  item.status === "in_progress" && "bg-accent/60 text-accent-foreground",
                  item.status === "completed" && "bg-success/5",
                  item.status === "pending" && "text-muted-foreground"
                )}
              >
                <TodoItemIcon status={item.status} />
                <span
                  className={cn(
                    "min-w-0 flex-1",
                    item.status === "completed" && "text-muted-foreground line-through",
                    item.status === "in_progress" && "text-foreground font-medium",
                    item.status === "pending" && "text-muted-foreground"
                  )}
                >
                  {item.content}
                </span>
                {item.status === "in_progress" ? (
                  <Badge className="mt-px" variant="warning">
                    In progress
                  </Badge>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground py-1 text-sm">No steps in this plan.</p>
        )}
      </CardContent>
    </Card>
  )
}

function PlanLookupRow({ activity, items }: { activity: ToolActivity; items: TodoToolItem[] }) {
  const label =
    activity.status === "running"
      ? "Checking the plan"
      : activity.status === "failed"
        ? "Couldn't check the plan"
        : "Checked the plan"
  const suffix =
    toolStatusSuffix(activity) ??
    (items.length > 0 ? completedLabel(countCompleted(items), items.length) : "No plan")

  return (
    <div
      aria-label="Plan lookup"
      className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs"
    >
      <ActivityStatusIcon fallbackIcon="tool" status={activity.status} />
      <ListTodoIcon className="size-3.5 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <ActivityStatusSuffix status={activity.status} suffix={suffix} />
    </div>
  )
}

function PlanUpdateBadge({ activity }: { activity: ToolActivity }) {
  if (activity.status === "running") {
    return <Badge variant="warning">Updating</Badge>
  }
  if (activity.status === "failed") {
    return <Badge variant="destructive">Update failed</Badge>
  }
  return null
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

function planDescription(activity: ToolActivity, items: TodoToolItem[]) {
  if (activity.status === "running") {
    return "Updating as the work progresses."
  }
  if (activity.status === "failed") {
    return "The latest update couldn't be saved."
  }
  if (items.length === 0) {
    return "Ready for the next steps."
  }
  const inProgress = items.find((item) => item.status === "in_progress")
  return inProgress ? `Now: ${inProgress.content}` : "Current steps and progress."
}

function countCompleted(items: TodoToolItem[]) {
  return items.filter((item) => item.status === "completed").length
}

function completedLabel(completedCount: number, itemCount: number) {
  return `${String(completedCount)} of ${String(itemCount)} done`
}
