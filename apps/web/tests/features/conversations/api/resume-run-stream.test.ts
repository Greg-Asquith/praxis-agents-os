// apps/web/tests/features/conversations/api/resume-run-stream.test.ts

import { afterEach, describe, expect, it, vi } from "vitest"

import { resumeRunStream } from "@/features/conversations/api/resume-run-stream"
import { parseApiError } from "@/lib/api/errors"
import { stubFetch, jsonResponse } from "../../../support/fetch-stub"

afterEach(() => vi.unstubAllGlobals())

describe("resume reservation conflicts", () => {
  it.each(["approval_already_reserved", "approval_decisions_conflict"])(
    "preserves %s and sends the approval POST once",
    async (code) => {
      const fetch = stubFetch(jsonResponse({ code }, { status: 409 }))
      const response = await resumeRunStream({
        runId: "root",
        payload: { approval_revision: "a".repeat(64), decisions: [] },
      })
      const error = await parseApiError(response)
      expect(error.problem?.["code"]).toBe(code)
      expect(fetch).toHaveBeenCalledOnce()
      expect(fetch.mock.calls[0]?.[1]?.method).toBe("POST")
    }
  )
})
