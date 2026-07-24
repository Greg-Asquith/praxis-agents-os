import { afterEach, describe, expect, it } from "vitest"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api"
import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"
import { setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  setActiveWorkspaceSlug(null)
})

describe("Gmail API query keys", () => {
  it("nests previews under connection details and scopes them to the active workspace", () => {
    setActiveWorkspaceSlug("acme")
    const acmeConnectionDetailKey = baseIntegrationQueryKeys.detail("connection-1")
    const acmeKey = gmailMessagePreviewQueryOptions("connection-1", "message-1").queryKey

    setActiveWorkspaceSlug("globex")
    const globexKey = gmailMessagePreviewQueryOptions("connection-1", "message-1").queryKey

    expect(acmeKey).toEqual([...acmeConnectionDetailKey, "gmail", "message-preview", "message-1"])
    expect(globexKey).not.toEqual(acmeKey)
  })
})
