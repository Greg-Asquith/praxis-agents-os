import { afterEach, describe, expect, it } from "vitest"

import { gmailMessagePreviewQueryOptions } from "@/integrations/gmail/api/message-preview"
import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"
import { setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  setActiveWorkspaceSlug(null)
})

describe("Gmail API query keys", () => {
  it("nests previews under the conversation and scopes them to the active workspace", () => {
    setActiveWorkspaceSlug("acme")
    const acmeBaseKey = baseIntegrationQueryKeys.workspace()
    const acmeKey = gmailMessagePreviewQueryOptions(
      "conversation-1",
      "hello@example.com",
      "message-1"
    ).queryKey

    setActiveWorkspaceSlug("globex")
    const globexKey = gmailMessagePreviewQueryOptions(
      "conversation-1",
      "hello@example.com",
      "message-1"
    ).queryKey

    expect(acmeKey).toEqual([
      ...acmeBaseKey,
      "conversation",
      "conversation-1",
      "gmail",
      "message-preview",
      "hello@example.com",
      "message-1",
    ])
    expect(globexKey).not.toEqual(acmeKey)
  })
})
