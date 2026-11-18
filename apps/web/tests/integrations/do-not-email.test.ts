// apps/web/tests/integrations/do-not-email.test.ts

import { describe, expect, it } from "vitest"

import { doNotEmailProblem } from "@/integrations/do-not-email"

const FIX = "Remove them."

describe("doNotEmailProblem", () => {
  it("blocks while a listed address is still a recipient and clears once it is removed", () => {
    const proposed = {
      _do_not_email: ["dana@example.com"],
      cc: ["Dana@Example.com"],
      to: ["kai@example.com"],
    }
    expect(doNotEmailProblem(proposed, FIX)).toContain("dana@example.com")
    expect(doNotEmailProblem({ ...proposed, cc: [] }, FIX)).toBeNull()
  })

  it("reads a saved draft's recipients from its review snapshot", () => {
    const draft = { _do_not_email: ["dana@example.com"], _draft: { bcc: ["dana@example.com"] } }
    expect(doNotEmailProblem(draft, FIX)).toContain("dana@example.com")
  })
})
