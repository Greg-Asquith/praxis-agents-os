import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

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

  it("renders removal in mobile and desktop rows while hiding your own action", () => {
    const html = renderToStaticMarkup(
      createElement(MembersTableContent, {
        memberships: [
          membership,
          { ...membership, id: "membership-2", user_id: "user-2", user_display_name: "Dana" },
        ],
        workspaceName: "Praxis",
        currentUserId: membership.user_id,
        onRemove: vi.fn(),
      })
    )

    expect(html.match(/aria-label="Remove Dana from workspace"/g)).toHaveLength(2)
    expect(html).not.toContain('aria-label="Remove Ada Lovelace from workspace"')
  })

  it("omits removal actions when management is unavailable", () => {
    expect(renderMembers([membership])).not.toContain("Remove")
  })
})

function renderMembers(memberships: (typeof membership)[]) {
  return renderToStaticMarkup(
    createElement(MembersTableContent, { memberships, workspaceName: "Praxis" })
  )
}
