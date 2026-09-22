import { createElement, type ReactNode, type MouseEvent } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { EntityFieldInput } from "@/components/tool-ui/entity-field-input"
import { Button } from "@/components/ui/button"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import type { ToolUiField } from "@/features/tools/types"
import { SharePointFileSource } from "@/integrations/sharepoint/components/file-source"
import {
  sharePointWriteFileArgs,
  sharePointUpdateFileArgs,
  validateSharePointWriteArgs,
} from "@/integrations/sharepoint/lib/write-args"
import { sharePointWriteFilePresenter } from "@/integrations/sharepoint/presenters/write-file"
import { sharePointUpdateFilePresenter } from "@/integrations/sharepoint/presenters/update-file"

vi.mock("@/components/ui/button", async (original) => {
  const module = await original<{ Button: typeof Button }>()
  return { ...module, Button: vi.fn(module.Button) }
})
vi.mock("@/components/tool-ui/entity-field-input", async (original) => {
  const module = await original<{ EntityFieldInput: typeof EntityFieldInput }>()
  return { ...module, EntityFieldInput: vi.fn(module.EntityFieldInput) }
})

const source = { version: 1, entity_kind: "file", entity_id: "private-file", label: "Report.xlsx" }
const details = {
  file_id: source.entity_id,
  name: "Report.xlsx",
  content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size_bytes: 1024,
  revision_id: "private-revision",
  content_hash: "private-hash",
  download_url: "private-download",
}
const target = {
  version: 1,
  entity_kind: "sharepoint_drive_item",
  drive_id: "private-drive",
  item_id: "private-item",
  kind: "file",
  label: "Report.xlsx",
}
const args = {
  name: "Report.xlsx",
  content: null,
  source,
  folder: null,
  _source: details,
  _library: "Operations",
  _target: { drive_id: "private-drive" },
}
const fields: ToolUiField[] = [
  {
    key: "content",
    label: "Content",
    format: "multiline",
    editable: true,
    secondary: true,
    min_rows: 0,
    options: [],
    placeholder: "",
  },
  {
    key: "source",
    label: "Source File",
    format: "entity",
    entity_kind: "file",
    editable: true,
    secondary: true,
    min_rows: 0,
    options: [],
    placeholder: "",
  },
]
const controls = (): ToolApprovalDecisionControls => ({
  decision: { decision: "pending", edits: {}, message: "" },
  error: null,
  onDecisionChange: vi.fn(),
  onRetry: vi.fn(),
  onReview: vi.fn(),
  pendingCount: 1,
  submitting: false,
})
function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } })
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(ToolConversationContext, { value: "conversation" }, node)
    )
  )
}
function button(label: string) {
  const match = vi.mocked(Button).mock.calls.find(([props]) => props.children === label)
  if (!match) throw new Error(`Missing button ${label}`)
  return match[0]
}

beforeEach(() => vi.clearAllMocks())

describe("SharePoint source approval", () => {
  it.each([
    ["sharepoint_write_file", sharePointWriteFilePresenter, args],
    [
      "sharepoint_update_file",
      sharePointUpdateFilePresenter,
      { ...args, file: target, expected_version: "private-etag" },
    ],
  ] as const)(
    "shows reviewed metadata and the existing File picker for %s",
    (name, presenter, input) => {
      const html = render(
        presenter.render({
          activity: {
            id: "call",
            kind: "approval",
            name,
            status: "awaiting_approval",
            args: input,
          },
          approvalDecision: controls(),
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "sharepoint",
          ui: {
            icon: "sharepoint",
            running_label: "Saving",
            completed_label: "Saved",
            failed_label: "Failed",
            approval_title: "Save",
            approval_prompt: "Review",
            approve_label: "Save",
            arg_fields: fields,
            result_fields: [],
          },
        })
      )
      expect(html).toContain("Report.xlsx")
      expect(html).toContain(details.content_type)
      expect(html).toContain("1.0 KB")
      expect(html).toContain("Review selected File")
      expect(html).not.toMatch(/private-(file|revision|hash|download)/)
      const picker = vi
        .mocked(EntityFieldInput)
        .mock.calls.find(([props]) => props.field.key === "source")?.[0]
      expect(picker?.field.entity_kind).toBe("file")
      expect(picker?.value).toEqual(source)
      expect(picker?.field.editable).toBe(true)
    }
  )

  it.each([
    [{ content: "Text" }, "Choose either text content or a workspace File, not both."],
    [{ source: null }, "Enter text content or choose a workspace File."],
    [
      { source: { ...source, entity_id: "other-file" } },
      "Review the selected File before approving.",
    ],
    [{ _source: null }, "Review the selected File before approving."],
    [{ _source: { ...details, size_bytes: -1 } }, "Review the selected File before approving."],
    [{ _source: { ...details, name: {} } }, "Review the selected File before approving."],
  ])("blocks invalid content or unreviewed sources %j", (patch, reason) => {
    expect(validateSharePointWriteArgs(sharePointWriteFileArgs({ ...args, ...patch }))).toBe(reason)
    expect(
      validateSharePointWriteArgs(
        sharePointUpdateFileArgs({ ...args, file: target, expected_version: "v1", ...patch })
      )
    ).toBe(reason)
  })

  it("accepts the reviewed File and ignores a changed display label", () => {
    expect(validateSharePointWriteArgs(sharePointWriteFileArgs(args))).toBeNull()
    expect(
      validateSharePointWriteArgs(
        sharePointWriteFileArgs({ ...args, source: { ...source, label: "Updated label" } })
      )
    ).toBeNull()
  })

  it.each([
    false,
    {},
    { ...source, entity_kind: "sharepoint_drive_item" },
    { ...source, entity_id: "" },
    { ...source, label: [] },
  ])("rejects malformed source references %j", (value) => {
    expect(sharePointWriteFileArgs({ ...args, source: value })).toBeNull()
  })

  it("escapes names and types and keeps private metadata out", () => {
    const parsed = sharePointWriteFileArgs({
      ...args,
      _source: {
        ...details,
        name: '<img src=x onerror="alert(1)">',
        content_type: "<script>alert(1)</script>",
      },
    })
    if (!parsed) throw new Error("Expected args")
    const html = render(
      createElement(SharePointFileSource, { args: parsed, controls: controls(), disabled: false })
    )
    expect(html).toContain("&lt;img")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toMatch(/<img|<script|private-/)
  })

  it("does not show the previous File metadata after another File is selected", () => {
    const parsed = sharePointWriteFileArgs({
      ...args,
      source: { ...source, entity_id: "other-file" },
    })
    if (!parsed) throw new Error("Expected args")
    const html = render(
      createElement(SharePointFileSource, { args: parsed, controls: controls(), disabled: false })
    )
    expect(html).not.toContain("Report.xlsx")
    expect(html).toContain("Review the selected File to check")
  })

  it("switches to text in one edit and keeps unrelated edits", () => {
    const parsed = sharePointWriteFileArgs(args)
    if (!parsed) throw new Error("Expected args")
    const control = controls()
    control.decision.edits = { name: "Renamed.txt" }
    render(
      createElement(SharePointFileSource, { args: parsed, controls: control, disabled: false })
    )
    button("Use text instead").onClick?.({
      ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
      preventBaseUIHandler: vi.fn(),
    })
    expect(control.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      message: "",
      edits: { name: "Renamed.txt", content: "", source: null },
    })
  })

  it("clears text before reviewing a File and builds executable arguments only", () => {
    const textArgs = { ...args, content: "Text", source: null }
    const parsed = sharePointWriteFileArgs(textArgs)
    if (!parsed) throw new Error("Expected args")
    const control = controls()
    render(
      createElement(SharePointFileSource, { args: parsed, controls: control, disabled: false })
    )
    button("Use a workspace File instead").onClick?.({
      ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
      preventBaseUIHandler: vi.fn(),
    })
    expect(control.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      message: "",
      edits: { content: null },
    })
    const replay = { name: args.name, content: "Text", source: null, folder: null }
    const payload = buildResumeDecisions(
      [
        {
          name: "sharepoint_write_file",
          tool_call_id: "call",
          args: textArgs,
          replay_args: replay,
        },
      ],
      { call: { decision: "approved", message: "", edits: { source, content: null } } },
      () => fields
    )
    expect(payload).toEqual([
      {
        tool_call_id: "call",
        decision: "approved",
        override_args: { ...replay, source, content: null },
      },
    ])
    expect(JSON.stringify(payload)).not.toMatch(/private-(revision|hash|download)/)
  })

  it("supports text edits from an initially null content field", () => {
    const replay = { name: args.name, content: null, source, folder: null }
    const payload = buildResumeDecisions(
      [{ name: "sharepoint_write_file", tool_call_id: "call", args, replay_args: replay }],
      {
        call: {
          decision: "approved",
          message: "",
          edits: { source: null, content: "Replacement text" },
        },
      },
      () => fields
    )
    expect(payload).toEqual([
      {
        tool_call_id: "call",
        decision: "approved",
        override_args: { ...replay, source: null, content: "Replacement text" },
      },
    ])
  })

  it("reviews only on an explicit click and disables the action during submission", () => {
    const parsed = sharePointWriteFileArgs(args)
    if (!parsed) throw new Error("Expected args")
    const control = controls()
    render(
      createElement(SharePointFileSource, { args: parsed, controls: control, disabled: false })
    )
    expect(control.onReview).not.toHaveBeenCalled()
    button("Review selected File").onClick?.({
      ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
      preventBaseUIHandler: vi.fn(),
    })
    expect(control.onReview).toHaveBeenCalledOnce()
    vi.clearAllMocks()
    render(createElement(SharePointFileSource, { args: parsed, controls: control, disabled: true }))
    expect(button("Review selected File").disabled).toBe(true)
    expect(button("Use text instead").disabled).toBe(true)
  })
})
