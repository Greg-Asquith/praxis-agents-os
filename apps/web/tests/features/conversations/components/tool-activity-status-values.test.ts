import { describe, expect, it } from "vitest"

import {
  toolActivityVerb,
  toolStatusSuffix,
} from "@/features/conversations/components/tool-activity-status-values"
import type { ToolActivity } from "@/features/conversations/message-parts"

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "tool-call-1",
    kind: "result",
    name: "write_file",
    status: "completed",
    ...overrides,
  }
}

describe("tool activity decision copy", () => {
  it("uses approve and decline language for settled decisions", () => {
    expect(toolStatusSuffix(activity({ decision: "approved" }))).toBe("· approved")
    expect(toolActivityVerb(activity({ status: "denied" }))).toBe("Declined")
    expect(toolStatusSuffix(activity({ decision: "denied", status: "denied" }))).toBe("· declined")
  })
})
