import type * as ReactModule from "react"
import type * as ReactQueryModule from "@tanstack/react-query"
import { isValidElement, type ReactElement, type ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { RetainedResult } from "@/components/tool-ui/retained-result"
import { Button } from "@/components/ui/button"

const state = vi.hoisted(() => ({
  opened: false,
  query: vi.fn<
    (options: { enabled: boolean; select: (data: unknown) => unknown }) => {
      isSuccess: boolean
      isFetching: boolean
      isError: boolean
      refetch?: () => void
      data?: unknown
    }
  >(),
  refetch: vi.fn(),
}))
vi.mock("react", async (original) => ({
  ...(await original<typeof ReactModule>()),
  useState: () => [
    state.opened,
    (opened: boolean) => {
      state.opened = opened
    },
  ],
}))
vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof ReactQueryModule>()),
  useQuery: state.query,
}))

const preview = { data: { rows: [1] }, fileId: "snapshot", fileName: "report.json", lists: [] }
const children = vi.fn((_data: unknown, _incomplete: boolean, control: ReactNode) => control)
const validate = vi.fn(() => true)
function render() {
  return RetainedResult({ children, preview, validate })
}
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap((child: ReactNode) => elements(child))
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...elements(node.props["children"] as ReactNode)]
}
function button(node: ReactNode) {
  const found = elements(node).find((item) => item.type === Button)
  if (!found) throw new Error("Missing complete-result control")
  return found
}

beforeEach(() => {
  vi.clearAllMocks()
  state.opened = false
  state.query.mockReturnValue({
    isSuccess: false,
    isFetching: false,
    isError: false,
    refetch: state.refetch,
  })
})

describe("complete-result interaction", () => {
  it("waits for a click before enabling the saved-result read", () => {
    const view = render()
    expect(state.query.mock.calls[0]?.[0]).toMatchObject({ enabled: false })
    expect(children.mock.lastCall?.slice(0, 2)).toEqual([preview.data, true])
    const click = button(view).props["onClick"] as () => void
    click()
    void render()
    expect(state.query.mock.lastCall?.[0]).toMatchObject({ enabled: true })
  })

  it("keeps the preview during loading and prevents duplicate requests", () => {
    state.opened = true
    state.query.mockReturnValue({ isSuccess: false, isFetching: true, isError: false })
    expect(button(render()).props).toMatchObject({
      disabled: true,
      children: "Loading complete result…",
    })
    expect(children.mock.lastCall?.slice(0, 2)).toEqual([preview.data, true])
  })

  it("keeps the preview on failure and retries from the same control", () => {
    state.opened = true
    state.query.mockReturnValue({
      isSuccess: false,
      isFetching: false,
      isError: true,
      refetch: state.refetch,
    })
    const view = render()
    expect(elements(view).some((item) => item.props["role"] === "alert")).toBe(true)
    expect(children.mock.lastCall?.slice(0, 2)).toEqual([preview.data, true])
    expect(button(view).props["children"]).toBe("Retry complete result")
    const click = button(view).props["onClick"] as () => void
    click()
    expect(state.refetch).toHaveBeenCalledOnce()
  })

  it("passes the complete data to the same presenter and removes the load control", () => {
    state.opened = true
    const data = { rows: [1, 2, 3] }
    state.query.mockReturnValue({ isSuccess: true, isFetching: false, isError: false, data })
    const view = render()
    expect(children.mock.lastCall?.slice(0, 2)).toEqual([data, false])
    expect(elements(view).some((item) => item.type === Button)).toBe(false)
    expect(elements(view).some((item) => item.props["role"] === "status")).toBe(true)
    const select = state.query.mock.lastCall?.[0].select as (value: unknown) => unknown
    expect(select(data)).toBe(data)
    validate.mockReturnValueOnce(false)
    expect(() => select(data)).toThrow("cannot be displayed")
  })
})
