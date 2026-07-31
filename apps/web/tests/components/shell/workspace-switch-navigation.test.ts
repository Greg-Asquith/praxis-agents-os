import { describe, expect, it } from "vitest"

import { shouldRedirectHomeForWorkspaceSwitch } from "@/components/shell/workspace-switch-navigation"

describe("workspace switch navigation", () => {
  it.each([
    "/conversations/new",
    "/conversations/conversation-1",
    "/agents/agent-1",
    "/artifacts/artifact-1",
    "/knowledge/document-1",
    "/schedules/schedule-1",
    "/skills/skill-1",
  ])("redirects workspace entity route %s", (pathname) => {
    expect(shouldRedirectHomeForWorkspaceSwitch(pathname)).toBe(true)
  })

  it("redirects an open workspace file", () => {
    expect(shouldRedirectHomeForWorkspaceSwitch("/files", { fileId: "file-1" })).toBe(true)
  })

  it.each([
    "/",
    "/agents",
    "/agents/new",
    "/artifacts",
    "/conversations",
    "/files",
    "/integrations/gmail",
    "/knowledge",
    "/schedules",
    "/schedules/new",
    "/skills",
    "/skills/new",
  ])("keeps workspace-safe route %s active", (pathname) => {
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
