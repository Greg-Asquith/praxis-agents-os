import {
  createElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
  type SyntheticEvent,
} from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { WorkspaceSettingsForm } from "@/features/workspaces/components/workspace-settings-form"
import type * as CardModule from "@/components/ui/card"

const state = vi.hoisted(() => ({
  personal: false,
  shared: false,
  role: "owner",
  update: vi.fn(),
  switchWorkspace: vi.fn(),
  submit: undefined as ((event: SyntheticEvent<HTMLFormElement>) => void) | undefined,
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      id: "team",
      slug: "team",
      name: "Example team",
      updated_at: "2026-09-24",
      is_personal: state.personal,
      conversations_shared_by_default: state.shared,
      current_user_role: state.role,
      icon_url: null,
    },
    workspaces: [],
    setWorkspaceBySlug: state.switchWorkspace,
  }),
}))
vi.mock("@/features/workspaces/api/update-workspace", () => ({
  useUpdateWorkspaceMutation: () => ({ mutateAsync: state.update, isPending: false }),
}))
vi.mock("@/features/workspaces/api/delete-workspace", () => ({
  useDeleteWorkspaceMutation: () => ({ isPending: false }),
}))
vi.mock("@/features/workspaces/api/workspace-icon", () => ({
  useCreateWorkspaceIconUploadMutation: () => ({ isPending: false }),
  useConfirmWorkspaceIconUploadMutation: () => ({ isPending: false }),
  useDeleteWorkspaceIconMutation: () => ({ isPending: false }),
}))
vi.mock("@/components/ui/confirm-dialog", () => ({ ConfirmDialog: () => null }))
vi.mock("@/components/ui/card", async (original) => ({
  ...(await original<typeof CardModule>()),
  Card: ({ children }: { children: ReactNode[] }) => {
    const form = children.find(
      (child) => isValidElement(child) && child.type === "form"
    ) as ReactElement<{ onSubmit: typeof state.submit }>
    state.submit = form.props.onSubmit
    return createElement("div", null, children)
  },
}))

beforeEach(() => {
  state.personal = false
  state.shared = false
  state.role = "owner"
  state.update.mockReset().mockResolvedValue({ slug: "team" })
  state.switchWorkspace.mockReset()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

it.each(["owner", "admin", "member", "read_only"] as const)(
  "shows the current value for %s with manager-only editing",
  (role) => {
    state.role = role
    state.shared = true
    const html = renderToStaticMarkup(createElement(WorkspaceSettingsForm))
    const control = /<[^>]*role="switch"[^>]*>/.exec(html)?.[0]
    expect(control).toBeDefined()
    expect(control).toContain('aria-checked="true"')
    expect(control?.includes('disabled=""')).toBe(role === "member" || role === "read_only")
    expect(html).toContain("Conversations shared by default")
    expect(html).toContain("Existing conversations are unchanged.")
  }
)

it("hides the setting in personal workspaces", () => {
  state.personal = true
  const html = renderToStaticMarkup(createElement(WorkspaceSettingsForm))
  expect(html).not.toContain('role="switch"')
  expect(html).not.toContain("Conversations shared by default")
})

it.each([true, false])("saves name and default sharing=%s together", async (shared) => {
  await submitForm(shared)
  expect(state.update).toHaveBeenCalledWith({
    workspaceId: "team",
    payload: { name: "Updated team", conversations_shared_by_default: shared },
  })
  await vi.waitFor(() => {
    expect(state.switchWorkspace).toHaveBeenCalledWith("team")
  })
})

it("omits the setting when saving a personal workspace", async () => {
  state.personal = true
  await submitForm(true)
  expect(state.update).toHaveBeenCalledWith({
    workspaceId: "team",
    payload: { name: "Updated team" },
  })
})

it.each(["member", "read_only"] as const)("does not submit as %s", async (role) => {
  state.role = role
  await submitForm(true)
  expect(state.update).not.toHaveBeenCalled()
})

async function submitForm(shared: boolean) {
  const formData = new FormData()
  formData.set("name", " Updated team ")
  if (shared) formData.set("conversations_shared_by_default", "on")
  vi.stubGlobal(
    "FormData",
    vi.fn(function () {
      return formData
    })
  )
  renderToStaticMarkup(createElement(WorkspaceSettingsForm))
  const target = {} as HTMLFormElement
  state.submit?.({
    nativeEvent: new Event("submit"),
    currentTarget: target,
    target,
    bubbles: true,
    cancelable: true,
    defaultPrevented: false,
    eventPhase: 2,
    isTrusted: false,
    preventDefault: vi.fn(),
    isDefaultPrevented: () => false,
    stopPropagation: vi.fn(),
    isPropagationStopped: () => false,
    persist: vi.fn(),
    timeStamp: 0,
    type: "submit",
  })
  await Promise.resolve()
}
