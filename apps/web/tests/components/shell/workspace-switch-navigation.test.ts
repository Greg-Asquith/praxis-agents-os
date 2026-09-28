import { describe, expect, it } from "vitest"

import { shouldRedirectHomeForWorkspaceSwitch } from "@/components/shell/workspace-switch-navigation"

describe("workspace switch navigation", () => {
  it.each(["/conversations/new", "/shared-chats/workspace-1/conversation-1"])(
    "redirects workspace entity route %s",
    (pathname) => {
      expect(shouldRedirectHomeForWorkspaceSwitch(pathname)).toBe(true)
    }
  )

  it("redirects an open workspace file", () => {
    expect(shouldRedirectHomeForWorkspaceSwitch("/files", { fileId: "file-1" })).toBe(true)
  })

  it("redirects an open workspace folder", () => {
    expect(shouldRedirectHomeForWorkspaceSwitch("/files", { folder: "folder-1" })).toBe(true)
  })

  it.each(["/", "/files", "/skills/new"])("keeps workspace-safe route %s active", (pathname) => {
    expect(shouldRedirectHomeForWorkspaceSwitch(pathname)).toBe(false)
  })

  it("keeps file list filters active when no file is open", () => {
    expect(
      shouldRedirectHomeForWorkspaceSwitch("/files", {
        direction: "asc",
        page: 2,
        sort: "name",
      })
    ).toBe(false)
  })
})
