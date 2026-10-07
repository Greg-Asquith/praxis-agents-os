import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type * as TableModule from "@/components/data-table/table"

import { MembersTableContent } from "@/features/workspaces/components/members-table"
import { InvitationsTableContent } from "@/features/workspaces/components/invitations-table"
import type {
  WorkspaceInvitationsListResponse,
  WorkspaceMembershipsListResponse,
} from "@/features/workspaces/types"

const view = vi.hoisted(() => ({ filter: "", sorting: [] as { id: string; desc: boolean }[] }))
vi.mock("@/components/data-table/table", async (importOriginal) => {
  const original = await importOriginal<typeof TableModule>()
  return {
    ...original,
    useAppTable: (options: Parameters<typeof original.useAppTable>[0]) =>
      original.useAppTable({
        ...options,
        state: { globalFilter: view.filter, sorting: view.sorting },
      }),
  }
})

const memberships: WorkspaceMembershipsListResponse["memberships"] = Array.from(
  { length: 12 },
  (_, index) => ({
    id: `member-${String(index)}`,
    workspace_id: "workspace-1",
    user_id: `user-${String(index)}`,
    user_display_name: `Person ${String(index).padStart(2, "0")}`,
    user_email: `person-${String(index).padStart(2, "0")}@example.com`,
    role: "member",
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    deleted: false,
    deleted_at: null,
  })
)
const invitations: WorkspaceInvitationsListResponse["invitations"] = memberships.map((member) => ({
  id: member.id,
  workspace_id: member.workspace_id,
  email: member.user_email ?? "",
  role: member.role,
  invited_by: "owner-1",
  expires_at: "2026-10-10T09:00:00Z",
  accepted_at: null,
  created_at: member.created_at,
  updated_at: member.updated_at,
  deleted: false,
  deleted_at: null,
}))

beforeEach(() => {
  view.filter = ""
  view.sorting = []
})

describe("workspace settings tables", () => {
  it("limits both desktop and mobile presentations to ten members", () => {
    const html = renderToStaticMarkup(
      createElement(MembersTableContent, { memberships, workspaceName: "Example" })
    )
    expect(html).toContain("person-09@example.com")
    expect(html).not.toContain("person-10@example.com")
  })

  it("finds a member by email beyond the first page", () => {
    view.filter = "PERSON-11@EXAMPLE.COM"
    const html = renderToStaticMarkup(
      createElement(MembersTableContent, { memberships, workspaceName: "Example" })
    )
    expect(html).toContain("person-11@example.com")
    expect(html).not.toContain("person-00@example.com")
  })

  it("sorts invitations before paginating both presentations", () => {
    view.sorting = [{ id: "email", desc: true }]
    const html = renderToStaticMarkup(
      createElement(InvitationsTableContent, { invitations, workspaceName: "Example" })
    )
    expect(html.indexOf("person-11@example.com")).toBeLessThan(
      html.indexOf("person-02@example.com")
    )
    expect(html).not.toContain("person-00@example.com")
    expect(html).not.toContain("person-01@example.com")
  })
})
