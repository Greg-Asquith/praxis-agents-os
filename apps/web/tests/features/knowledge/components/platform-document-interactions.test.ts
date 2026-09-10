// apps/web/tests/features/knowledge/components/platform-document-interactions.test.ts

import type * as ReactModule from "react"
import { isValidElement, type ReactElement, type ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Dialog } from "@/components/ui/dialog"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import { PlatformDocumentActions } from "@/features/knowledge/components/platform-document-actions"
import { CopyDocumentButton } from "@/features/knowledge/components/copy-document-button"
import type { KbDocumentDetail } from "@/features/knowledge/types"

const state = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  publish: vi.fn(),
  copy: vi.fn(),
  navigate: vi.fn(),
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
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => state.navigate }))
vi.mock("@/features/knowledge/api/platform-publish-document", () => ({
  usePlatformPublishDocumentMutation: () => ({ mutateAsync: state.publish, isPending: false }),
}))
vi.mock("@/features/knowledge/api/platform-withdraw-document", () => ({
  usePlatformWithdrawDocumentMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock("@/features/knowledge/api/platform-reprocess-document", () => ({
  usePlatformReprocessDocumentMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock("@/features/knowledge/api/platform-delete-document", () => ({
  usePlatformDeleteDocumentMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock("@/features/knowledge/api/copy-document", () => ({
  useCopyDocumentMutation: () => ({ mutateAsync: state.copy, isPending: false }),
}))
vi.mock("@/features/knowledge/components/manual-document-form", () => ({
  ManualDocumentForm: () => null,
}))

const document: KbDocumentDetail = {
  id: "shared-document",
  title: "Policy",
  scope: "platform",
  workspace_id: null,
  is_published: false,
  can_manage_platform: true,
  source_type: "manual",
  status: "ready",
  source_sync_status: null,
  source_synced_at: null,
  processing_error: null,
  processing_attempts: 1,
  is_private: false,
  chunk_count: 1,
  created_by_user_id: null,
  created_at: "2026-09-10",
  updated_at: "2026-09-10",
  concept_id: null,
  source_updated_at: null,
  summary: null,
  external_url: null,
  content_md: {
    node: "praxis_untrusted",
    source_kind: "kb",
    source_ref: "document:shared-document",
    content: "Reviewed policy",
  },
  meta: { ingestion_version: "version-a" },
}

function render(
  component: typeof CopyDocumentButton | typeof PlatformDocumentActions,
  value = document
) {
  state.cursor = 0
  return component({ document: value })
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

function button(node: ReactNode, label: string) {
  const matches = elements(node).filter(
    (item) => item.type === Button && item.props["children"] === label
  )
  const element = matches.at(-1)
  if (!element) throw new Error(`Expected button: ${label}`)
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
  state.publish.mockReset().mockResolvedValue(document)
  state.copy.mockReset().mockResolvedValue({ id: "local-copy" })
  state.navigate.mockReset().mockResolvedValue(undefined)
})

describe("platform Knowledge confirmation interactions", () => {
  it("publishes the opened review version after a background update changes the document", async () => {
    await invoke(button(render(PlatformDocumentActions), "Publish"), "onClick")
    const updated = { ...document, meta: { ingestion_version: "version-b" } }
    const confirmation = propsOf(render(PlatformDocumentActions, updated), ConfirmDialog)
    expect(confirmation["open"]).toBe(true)
    await invoke(confirmation, "onConfirm")
    expect(state.publish).toHaveBeenCalledWith({
      documentId: document.id,
      expectedIngestionVersion: "version-a",
    })
    expect(propsOf(render(PlatformDocumentActions, updated), ConfirmDialog)["open"]).toBe(false)
  })

  it("retains the confirmation and reviewed version after rejected publication", async () => {
    state.publish.mockRejectedValue(new Error("Review the latest document"))
    await invoke(button(render(PlatformDocumentActions), "Publish"), "onClick")
    await invoke(propsOf(render(PlatformDocumentActions), ConfirmDialog), "onConfirm")
    const confirmation = propsOf(render(PlatformDocumentActions), ConfirmDialog)
    expect(confirmation["open"]).toBe(true)
    expect(
      elements(confirmation["description"] as ReactNode).some(
        (item) =>
          item.props["role"] === "alert" && item.props["children"] === "Review the latest document"
      )
    ).toBe(true)
    expect(state.publish).toHaveBeenCalledWith({
      documentId: document.id,
      expectedIngestionVersion: "version-a",
    })
  })

  it.each([true, false])(
    "copies canonical content with private choice %s and opens the local document",
    async (isPrivate) => {
      const opening = elements(render(CopyDocumentButton)).find(
        (item) => item.type === Button && Array.isArray(item.props["children"])
      )
      if (!opening) throw new Error("Missing copy trigger")
      await invoke(opening.props, "onClick")
      let tree = render(CopyDocumentButton)
      expect(propsOf(tree, PrivacyField)["checked"]).toBe(true)
      if (!isPrivate) {
        await invoke(propsOf(tree, PrivacyField), "onCheckedChange", false)
        tree = render(CopyDocumentButton)
      }
      await invoke(button(tree, "Make a workspace copy"), "onClick")
      expect(state.copy).toHaveBeenCalledWith({
        title: "Policy",
        contentMd: "Reviewed policy",
        isPrivate,
      })
      expect(state.navigate).toHaveBeenCalledWith({
        to: "/knowledge/$documentId",
        params: { documentId: "local-copy" },
        search: {},
      })
      expect(propsOf(render(CopyDocumentButton), Dialog)["open"]).toBe(false)
    }
  )

  it("keeps a failed copy open with its privacy choice and an actionable error", async () => {
    state.copy.mockRejectedValue(new Error("Try copying again"))
    const opening = elements(render(CopyDocumentButton)).find(
      (item) => item.type === Button && Array.isArray(item.props["children"])
    )
    if (!opening) throw new Error("Missing copy trigger")
    await invoke(opening.props, "onClick")
    await invoke(propsOf(render(CopyDocumentButton), PrivacyField), "onCheckedChange", false)
    await invoke(button(render(CopyDocumentButton), "Make a workspace copy"), "onClick")
    const tree = render(CopyDocumentButton)
    expect(propsOf(tree, Dialog)["open"]).toBe(true)
    expect(propsOf(tree, PrivacyField)["checked"]).toBe(false)
    expect(
      elements(tree).some(
        (item) => item.props["role"] === "alert" && item.props["children"] === "Try copying again"
      )
    ).toBe(true)
    expect(state.navigate).not.toHaveBeenCalled()
  })
})
