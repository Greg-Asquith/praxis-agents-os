// apps/web/src/features/conversations/todo-tools.ts

import type { ToolActivity } from "@/features/conversations/message-parts"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import { isRecord } from "@/lib/guards"

export const WRITE_TODOS_TOOL_NAME = "write_todos"
const READ_TODOS_TOOL_NAME = "read_todos"

type TodoToolStatus = "pending" | "in_progress" | "completed"

export type TodoToolItem = {
  content: string
  status: TodoToolStatus
}

export function isTodoToolActivity(activity: ToolActivity): boolean {
  return activity.name === WRITE_TODOS_TOOL_NAME || activity.name === READ_TODOS_TOOL_NAME
}

export function todoItemsFromActivity(activity: ToolActivity): TodoToolItem[] | null {
  return todoItems(activity.result) ?? todoItems(normalizeToolArgs(activity.args))
}

function todoItems(value: unknown): TodoToolItem[] | null {
  const record = unwrapToolReturnValue(value)
  if (!isRecord(record) || !Array.isArray(record["items"])) {
    return null
  }
  const items = record["items"].map(todoItem)
  if (items.some((item) => item === null)) {
    return null
  }
  return items.filter((item) => item !== null)
}

function todoItem(value: unknown): TodoToolItem | null {
  if (!isRecord(value)) {
    return null
  }
  const content = value["content"]
  const status = value["status"]
  if (typeof content !== "string" || !content.trim()) {
    return null
  }
  if (status !== "pending" && status !== "in_progress" && status !== "completed") {
    return null
  }
  return { content, status }
}

function unwrapToolReturnValue(value: unknown): unknown {
  if (!isRecord(value)) {
    return value
  }
  return isRecord(value["return_value"]) ? value["return_value"] : value
}
