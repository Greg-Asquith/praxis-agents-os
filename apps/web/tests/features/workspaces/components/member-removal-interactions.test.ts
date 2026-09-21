import type * as ReactModule from "react"
import type * as ReactQueryModule from "@tanstack/react-query"
import { isValidElement, type ReactElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MembersTable, MembersTableContent } from "@/features/workspaces/components/members-table"
import type { Workspace, WorkspaceMembershipsListResponse } from "@/features/workspaces/types"

const state = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  remove: vi.fn(),
  pending: false,
  superAdmin: false,
  workspace: {} as Workspace,
}))

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof ReactModule>()),
  useState: (initial: unknown) => {
    const index = state.cursor++
    if (state.slots.length <= index) state.slots[index] = initial
    return [
      state.slots[index],
      (value: unknown) => {
        state.slots[index] = value
      },
    ]
  },
}))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof ReactQueryModule>()),
  useSuspenseQuery: () => ({ data: { id: "current-user", is_super_admin: state.superAdmin } }),
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({ workspace: state.workspace }),
}))
vi.mock("@/features/workspaces/api/list-memberships", () => ({
  useWorkspaceMembershipsQuery: () => ({ data: { memberships: [] } }),
}))
vi.mock("@/features/workspaces/api/delete-membership", () => ({
  useDeleteMembershipMutation: () => ({ mutateAsync: state.remove, isPending: state.pending }),
}))

const member: WorkspaceMembershipsListResponse["memberships"][number] = {
  id: "membership-2",
  workspace_id: "workspace-1",
  user_id: "user-2",
  user_display_name: "Dana",
  user_email: "dana@example.com",
  role: "member",
  created_at: "2026-09-21T09:00:00Z",
  updated_at: "2026-09-21T09:00:00Z",
  deleted: false,
  deleted_at: null,
}

function render() {
  state.cursor = 0
  return MembersTable()
}

function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap((child: ReactNode) => elements(child))
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...elements(node.props["children"] as ReactNode)]
}

function propsOf(node: ReactNode, type: unknown) {
  const element = elements(node).find((item) => item.type === type)
  if (!element) throw new Error("Expected control was not rendered")
  return element.props
}

async function invoke(props: Record<string, unknown>, name: string, value?: unknown) {
  const callback = props[name]
  if (typeof callback !== "function") throw new Error(`Expected callback: ${name}`)
  await (callback as (value?: unknown) => unknown)(value)
}

beforeEach(() => {
  state.slots = []
  state.cursor = 0
  state.pending = false
  state.superAdmin = false
  state.remove.mockReset().mockResolvedValue(undefined)
  state.workspace = {
    id: "workspace-1",
    slug: "example",
    name: "Example Organisation",
    icon_url: null,
    is_personal: false,
    status: "active",
    current_user_role: "admin",
    created_at: "2026-09-21T09:00:00Z",
    updated_at: "2026-09-21T09:00:00Z",
    deleted: false,
    deleted_at: null,
  }
})

describe("workspace member removal confirmation", () => {
  it("opens a named confirmation and cancels without sending a request", async () => {
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    const confirmation = propsOf(render(), ConfirmDialog)
    expect(confirmation["open"]).toBe(true)
    const description = renderToStaticMarkup(confirmation["description"] as ReactNode)
    expect(description).toContain("Dana (dana@example.com) loses access to Example Organisation")
    expect(description).toContain("Their account and access to other workspaces remain")

    await invoke(confirmation, "onOpenChange", false)

    expect(propsOf(render(), ConfirmDialog)["open"]).toBe(false)
    expect(state.remove).not.toHaveBeenCalled()
  })

  it("removes the confirmed membership and closes after success", async () => {
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    expect(state.remove).not.toHaveBeenCalled()
    await invoke(propsOf(render(), ConfirmDialog), "onConfirm")

    expect(state.remove).toHaveBeenCalledExactlyOnceWith({
      workspaceId: "workspace-1",
      membershipId: "membership-2",
    })
    expect(propsOf(render(), ConfirmDialog)["open"]).toBe(false)
  })

  it("keeps the selected member and error visible after a rejected removal", async () => {
    state.remove.mockRejectedValue(new Error("Add another owner before removing this member."))
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    await invoke(propsOf(render(), ConfirmDialog), "onConfirm")
    const confirmation = propsOf(render(), ConfirmDialog)

    expect(confirmation["open"]).toBe(true)
    expect(renderToStaticMarkup(confirmation["description"] as ReactNode)).toContain(
      "Add another owner before removing this member."
    )
    expect(
      elements(confirmation["description"] as ReactNode).some(
        (element) => element.props["role"] === "alert"
      )
    ).toBe(true)
  })

  it("marks pending confirmation and prevents another request", async () => {
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    state.pending = true
    const confirmation = propsOf(render(), ConfirmDialog)
    expect(confirmation["isPending"]).toBe(true)
    expect(confirmation["confirmPendingLabel"]).toBe("Removing…")
    await invoke(confirmation, "onConfirm")
    expect(state.remove).not.toHaveBeenCalled()
  })

  it("closes a selection from another workspace and prevents its removal", async () => {
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    state.workspace = { ...state.workspace, id: "workspace-2", name: "Other workspace" }
    const confirmation = propsOf(render(), ConfirmDialog)
    expect(confirmation["open"]).toBe(false)
    await invoke(confirmation, "onConfirm")
    expect(state.remove).not.toHaveBeenCalled()
  })

  it("removes controls and blocks confirmation when management access changes", async () => {
    await invoke(propsOf(render(), MembersTableContent), "onRemove", member)
    state.workspace = { ...state.workspace, current_user_role: "read_only" }
    const tree = render()
    expect(propsOf(tree, MembersTableContent)["onRemove"]).toBeUndefined()
    expect(propsOf(tree, ConfirmDialog)["open"]).toBe(false)
    await invoke(propsOf(tree, ConfirmDialog), "onConfirm")
    expect(state.remove).not.toHaveBeenCalled()
  })

  it("provides removal controls for a super admin with read-only membership", () => {
    state.superAdmin = true
    state.workspace = { ...state.workspace, current_user_role: "read_only" }
    expect(propsOf(render(), MembersTableContent)["onRemove"]).toBeTypeOf("function")
  })
})
