import { describe, expect, it } from "vitest"

import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"

describe("mergeApprovalArgs", () => {
  it("overlays current approval edits without mutating the original arguments", () => {
    const args = { action: "LINK", campaign_ids: ["10"], locked: "kept" }
    const edits = { action: "UNLINK", campaign_ids: ["20"] }

    expect(mergeApprovalArgs(args, edits)).toEqual({
      action: "UNLINK",
      campaign_ids: ["20"],
      locked: "kept",
    })
    expect(args).toEqual({ action: "LINK", campaign_ids: ["10"], locked: "kept" })
  })

  it("leaves non-record arguments unchanged", () => {
    expect(mergeApprovalArgs(null, { action: "UNLINK" })).toBeNull()
    expect(mergeApprovalArgs(["10"], { action: "UNLINK" })).toEqual(["10"])
  })
})
