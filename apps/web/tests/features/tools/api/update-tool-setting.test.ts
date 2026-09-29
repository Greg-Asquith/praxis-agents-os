import { afterEach, expect, it, vi } from "vitest"

import { updateToolSetting } from "@/features/tools/api/update-tool-setting"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../../support/fetch-stub"

afterEach(() => {
  vi.unstubAllGlobals()
})

it("keeps an Off tool disabled when its new approval policy fails to save", async () => {
  const server = { enabled: false, policy: null as unknown }
  let failPolicy = true
  const fetchStub = stubFetch((_input, init) => {
    const { url } = getFetchRequest(fetchStub, fetchStub.mock.calls.length - 1)
    const body = getJsonRequestBody(init ?? {}) as Record<string, unknown>
    if (url.pathname.endsWith("/policy")) {
      if (failPolicy) return jsonResponse({ title: "Invalid" }, { status: 422 })
      server.policy = body["policy"]
    } else {
      server.enabled = body["enabled"] === true
    }
    return jsonResponse({})
  })

  await expect(
    updateToolSetting({ toolName: "web_search", policy: "approval", enabled: true })
  ).rejects.toThrow()
  expect(server).toEqual({ enabled: false, policy: null })

  failPolicy = false
  await updateToolSetting({ toolName: "web_search", policy: "approval", enabled: true })
  expect(server).toEqual({ enabled: true, policy: "approval" })
})
