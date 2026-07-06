// apps/web/src/features/conversations/todo-tools.test.ts

import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/features/conversations/message-parts"
import { todoItemsFromActivity } from "@/features/conversations/todo-tools"

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return { id: "t1", kind: "call", status: "completed", name: "write_todos", ...overrides }
}

describe("todoItemsFromActivity", () => {
  it("parses items from a tool result", () => {
    const items = todoItemsFromActivity(
      activity({
        result: {
          items: [
            { content: "Draft the report", status: "completed" },
            { content: "Review it", status: "in_progress" },
          ],
          counts: { pending: 0, in_progress: 1, completed: 1 },
        },
      })
    )
    expect(items).toEqual([
      { content: "Draft the report", status: "completed" },
      { content: "Review it", status: "in_progress" },
    ])
  })

  it("falls back to JSON-string args while the call is still running", () => {
    const items = todoItemsFromActivity(
      activity({
        status: "running",
        args: JSON.stringify({ items: [{ content: "Plan the work", status: "pending" }] }),
      })
    )
    expect(items).toEqual([{ content: "Plan the work", status: "pending" }])
  })

  it("returns an empty list for a cleared plan", () => {
    expect(todoItemsFromActivity(activity({ result: { items: [] } }))).toEqual([])
  })

  it("returns null when any item is malformed", () => {
    const items = todoItemsFromActivity(
      activity({
        result: {
          items: [
            { content: "ok", status: "pending" },
            { content: "", status: "bad" },
          ],
        },
      })
    )
    expect(items).toBeNull()
  })

  it("returns null when neither result nor args carry items", () => {
    expect(todoItemsFromActivity(activity({ result: "done", args: "{}" }))).toBeNull()
  })
})
