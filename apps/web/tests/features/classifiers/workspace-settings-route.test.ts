import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

let role = "owner"

vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: { current_user_role: role },
  }),
}))
vi.mock("@/features/classifiers/components/classifiers-settings-panel", () => ({
  ClassifiersSettingsPanel: () => createElement("div", null, "Classifier settings panel"),
}))
vi.mock("@/features/audit/components/audit-settings-panel", () => ({
  AuditSettingsPanel: () => createElement("div", null, "Audit settings panel"),
}))
vi.mock("@/features/usage/components/usage-dashboard-panel", () => ({
  UsageSettingsPanel: () => createElement("div", null, "Usage settings panel"),
}))
vi.mock("@/features/workspaces/components/invitations-table", () => ({
  InvitationsTable: () => createElement("div", null, "Invitations table"),
}))
vi.mock("@/features/workspaces/components/members-table", () => ({
  MembersTable: () => createElement("div", null, "Members table"),
}))
vi.mock("@/features/workspaces/components/workspace-settings-form", () => ({
  WorkspaceSettingsForm: () => createElement("div", null, "Workspace details"),
}))
vi.mock("@/features/workspaces/components/workspace-role-badge", () => ({
  WorkspaceRoleBadge: () => createElement("span", null, "Workspace role"),
}))

import { WorkspaceSettingsRoute } from "@/features/workspaces/routes/workspace-settings-route"

beforeEach(() => {
  role = "owner"
})

describe("WorkspaceSettingsRoute classifier tab", () => {
  it("shows classifier management to owners and admins", () => {
    expect(renderRoute()).toContain("Classifiers")
    role = "admin"
    expect(renderRoute()).toContain("Classifiers")
  })

  it("hides classifier management from roles that cannot manage the workspace", () => {
    role = "member"
    expect(renderRoute()).not.toContain("Classifiers")
  })
})

function renderRoute() {
  return renderToStaticMarkup(createElement(WorkspaceSettingsRoute))
}
