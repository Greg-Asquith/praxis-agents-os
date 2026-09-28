// apps/web/tests/features/knowledge/components/platform-document-interactions.test.ts

import type * as ReactModule from "react"
import { isValidElement, type ReactElement, type ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { PlatformDocumentActions } from "@/features/knowledge/components/platform-document-actions"
import type { CopyDocumentButton } from "@/features/knowledge/components/copy-document-button"
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
})
