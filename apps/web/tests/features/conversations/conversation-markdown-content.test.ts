import { describe, expect, it } from "vitest"

import { workspaceFileIdFromHref } from "@/features/conversations/file-links"

const FILE_ID = "245de7d6-0963-4ba4-9b63-45fe64526252"

describe("workspaceFileIdFromHref", () => {
  it("accepts only the internal workspace-file route with a UUID", () => {
    expect(workspaceFileIdFromHref(`/files?fileId=${FILE_ID}`)).toBe(FILE_ID)
    expect(workspaceFileIdFromHref(`/files?page=2&fileId=${FILE_ID}`)).toBe(FILE_ID)
  })

  it("does not intercept malformed or external links", () => {
    expect(workspaceFileIdFromHref("/files?fileId=not-a-uuid")).toBeNull()
    expect(workspaceFileIdFromHref(`/artifacts/${FILE_ID}`)).toBeNull()
    expect(workspaceFileIdFromHref(`https://example.com/files?fileId=${FILE_ID}`)).toBeNull()
  })
})
