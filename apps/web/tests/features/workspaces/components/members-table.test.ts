import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { MembersTableContent } from "@/features/workspaces/components/members-table"

const membership = {
  created_at: "2026-08-12T09:00:00Z",
  deleted: false,
  deleted_at: null,
  id: "membership-1",
  role: "owner" as const,
  updated_at: "2026-08-12T09:00:00Z",
  user_display_name: "Ada Lovelace",
  user_email: "ada@example.com",
  user_id: "user-1",
  workspace_id: "workspace-1",
}

describe("MembersTable", () => {
  it("renders app-table headers and a member row", () => {
    const html = renderMembers([membership])

    expect(html).toContain("People who can access Praxis.")
    expect(html).toContain(">User<")
    expect(html).toContain(">Role<")
    expect(html).toContain(">Added<")
    expect(html.match(/Ada Lovelace/g)).toHaveLength(2)
    expect(html).toContain("ada@example.com")
    expect(html).toContain("Owner")
  })

  it("keeps the existing empty state", () => {
    const html = renderMembers([])

    expect(html).toContain("No members yet")
    expect(html).toContain("Workspace members will appear here after they accept access.")
    expect(html).not.toContain("<table")
  })
})

function renderMembers(memberships: (typeof membership)[]) {
  return renderToStaticMarkup(
    createElement(MembersTableContent, { memberships, workspaceName: "Praxis" })
  )
}
