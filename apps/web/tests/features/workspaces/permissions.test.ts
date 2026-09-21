import { describe, expect, it } from "vitest"

import { canRemoveWorkspaceMembers } from "@/features/workspaces/permissions"
import type { Workspace, WorkspaceRole } from "@/features/workspaces/types"

const workspace: Workspace = {
  id: "workspace-1",
  slug: "example",
  name: "Example",
  icon_url: null,
  is_personal: false,
  status: "active",
  current_user_role: "admin",
  created_at: "2026-09-21T09:00:00Z",
  updated_at: "2026-09-21T09:00:00Z",
  deleted: false,
  deleted_at: null,
}

describe("workspace member removal permissions", () => {
  it.each<[WorkspaceRole | null, boolean, boolean]>([
    ["owner", false, true],
    ["admin", false, true],
    ["member", false, false],
    ["read_only", false, false],
    ["member", true, true],
    ["read_only", true, true],
    [null, false, false],
    [null, true, false],
  ])("checks role %s with super admin %s", (role, isSuperAdmin, expected) => {
    expect(canRemoveWorkspaceMembers({ ...workspace, current_user_role: role }, isSuperAdmin)).toBe(
      expected
    )
  })

  it.each([false, true])("protects personal workspaces with super admin %s", (isSuperAdmin) => {
    expect(
      canRemoveWorkspaceMembers(
        { ...workspace, is_personal: true, current_user_role: "owner" },
        isSuperAdmin
      )
    ).toBe(false)
  })
})
