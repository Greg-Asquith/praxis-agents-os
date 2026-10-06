import type * as ReactModule from "react"
import { isValidElement, type ReactElement, type ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  InvitationsTable,
  InvitationsTableContent,
} from "@/features/workspaces/components/invitations-table"
import type { Workspace, WorkspaceInvitationsListResponse } from "@/features/workspaces/types"

const state = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  revoke: vi.fn(),
  pending: false,
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
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({ workspace: state.workspace }),
}))
vi.mock("@/features/workspaces/api/list-invitations", () => ({
  useWorkspaceInvitationsQuery: () => ({ data: { invitations: [] } }),
}))
vi.mock("@/features/workspaces/api/delete-invitation", () => ({
  useDeleteInvitationMutation: () => ({ mutateAsync: state.revoke, isPending: state.pending }),
}))

const invitation: WorkspaceInvitationsListResponse["invitations"][number] = {
  id: "invitation-2",
  workspace_id: "workspace-1",
  email: "dana@example.com",
  invited_by: "owner-1",
  expires_at: "2026-10-10T09:00:00Z",
  accepted_at: null,
  role: "member",
  created_at: "2026-09-21T09:00:00Z",
  updated_at: "2026-09-21T09:00:00Z",
  deleted: false,
  deleted_at: null,
}

function render() {
  state.cursor = 0
  return InvitationsTable()
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
  state.revoke.mockReset().mockResolvedValue(undefined)
  state.workspace = {
    id: "workspace-1",
    slug: "example",
    name: "Example Organisation",
    icon_url: null,
    is_personal: false,
    conversations_shared_by_default: false,
    default_model_provider: null,
    default_model: null,
    status: "active",
    current_user_role: "admin",
    created_at: "2026-09-21T09:00:00Z",
    updated_at: "2026-09-21T09:00:00Z",
    deleted: false,
    deleted_at: null,
  }
})

describe("workspace invitation revocation confirmation", () => {
  it("closes a selection from another workspace and prevents its revocation", async () => {
    await invoke(propsOf(render(), InvitationsTableContent), "onRevoke", invitation)
    state.workspace = { ...state.workspace, id: "workspace-2", name: "Other workspace" }
    const confirmation = propsOf(render(), ConfirmDialog)
    expect(confirmation["open"]).toBe(false)
    await invoke(confirmation, "onConfirm")
    expect(state.revoke).not.toHaveBeenCalled()
  })

  it("removes controls and blocks confirmation when management access changes", async () => {
    await invoke(propsOf(render(), InvitationsTableContent), "onRevoke", invitation)
    state.workspace = { ...state.workspace, current_user_role: "read_only" }
    const tree = render()
    expect(propsOf(tree, InvitationsTableContent)["onRevoke"]).toBeUndefined()
    expect(propsOf(tree, ConfirmDialog)["open"]).toBe(false)
    await invoke(propsOf(tree, ConfirmDialog), "onConfirm")
    expect(state.revoke).not.toHaveBeenCalled()
  })

  it("retains the selection after failure and closes it after a successful retry", async () => {
    await invoke(propsOf(render(), InvitationsTableContent), "onRevoke", invitation)
    state.revoke.mockRejectedValueOnce(new Error("Revocation failed"))
    await invoke(propsOf(render(), ConfirmDialog), "onConfirm")
    expect(propsOf(render(), ConfirmDialog)["open"]).toBe(true)
    await invoke(propsOf(render(), ConfirmDialog), "onConfirm")
    expect(state.revoke).toHaveBeenLastCalledWith({
      workspaceId: "workspace-1",
      invitationId: "invitation-2",
    })
    expect(propsOf(render(), ConfirmDialog)["open"]).toBe(false)
  })
})
