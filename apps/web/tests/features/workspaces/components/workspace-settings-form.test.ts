import {
  createElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
  type SyntheticEvent,
} from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, expect, it, vi } from "vitest"

import { WorkspaceSettingsForm } from "@/features/workspaces/components/workspace-settings-form"
import type * as CardModule from "@/components/ui/card"

const state = vi.hoisted(() => ({
  update: vi.fn(),
  submit: undefined as ((event: SyntheticEvent<HTMLFormElement>) => void) | undefined,
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      id: "team",
      slug: "team",
      name: "Example team",
      updated_at: "2026-09-24",
      is_personal: false,
      conversations_shared_by_default: false,
      default_model_provider: null,
      default_model: null,
      current_user_role: "admin",
      icon_url: null,
    },
    workspaces: [],
    setWorkspaceBySlug: vi.fn(),
  }),
}))
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: undefined }) }))
vi.mock("@/features/models/api/list-model-catalog", () => ({
  modelCatalogQueryOptions: () => ({}),
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

afterEach(() => {
  vi.unstubAllGlobals()
})

it("sends the default sharing switch value in the workspace update", async () => {
  state.update.mockResolvedValue({ slug: "team" })

  for (const shared of [true, false]) {
    state.update.mockClear()
    await submitForm(shared)
    expect(state.update).toHaveBeenCalledWith({
      workspaceId: "team",
      payload: { name: "Updated team", conversations_shared_by_default: shared },
    })
  }
})

async function submitForm(shared: boolean) {
  vi.unstubAllGlobals()
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
