// apps/web/tests/integrations/sharepoint/write-presenters.test.ts

import { createElement, type ChangeEvent, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { EntityFieldInput } from "@/components/tool-ui/entity-field-input"
import { entityReferenceHydrationQueryOptions } from "@/components/tool-ui/entity-reference-queries"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolUiField } from "@/features/tools/types"
import type { ToolRowPresenterProps } from "@/integrations/contract"
import { loadIntegrationUiModules } from "@/integrations/registry"
import {
  sharePointWriteFileArgs,
  validateSharePointWriteArgs,
} from "@/integrations/sharepoint/lib/write-args"

vi.mock("@/components/ui/input", async (importOriginal) => {
  const original = await importOriginal<{ Input: typeof Input }>()
  return { ...original, Input: vi.fn(original.Input) }
})
vi.mock("@/components/ui/textarea", async (importOriginal) => {
  const original = await importOriginal<{ Textarea: typeof Textarea }>()
  return { ...original, Textarea: vi.fn(original.Textarea) }
})
vi.mock("@/components/tool-ui/entity-field-input", async (importOriginal) => {
  const original = await importOriginal<{ EntityFieldInput: typeof EntityFieldInput }>()
  return { ...original, EntityFieldInput: vi.fn(original.EntityFieldInput) }
})

const reference = {
  version: 1,
  entity_kind: "sharepoint_drive_item",
  drive_id: "private-drive",
  item_id: "private-item",
  kind: "file",
  label: "Reports / report.txt",
}
const folder = { ...reference, kind: "folder", label: "Reports / Monthly" }
const metadata = {
  _library: "Operations library",
  _target: { drive_id: reference.drive_id, resource_id: "private-resource" },
}
const argsByName: Record<string, Record<string, unknown>> = {
  sharepoint_create_folder: { name: "Reports", parent: null, ...metadata },
  sharepoint_write_file: {
    name: "report.txt",
    content: "Reviewed text",
    folder: null,
    ...metadata,
  },
  sharepoint_update_file: {
    file: reference,
    expected_version: '"version-1"',
    content: "Reviewed replacement",
    ...metadata,
  },
}
const node = (content: string) => ({
  node: "praxis_untrusted",
  content,
  source_kind: "sharepoint_drive_item",
  source_ref: "private-source",
})
const item = {
  name: node("Saved report.txt"),
  kind: "file",
  path: node("/Reports/Monthly"),
  size_bytes: 1024,
  content_type: node("text/plain"),
  modified_at: node("2026-09-21T10:00:00Z"),
  web_url: node("https://example.sharepoint.com/Reports/report.txt"),
  reference,
  version: '"private-version"',
  uploadUrl: "PRIVATE_UPLOAD_URL",
  downloadUrl: "PRIVATE_DOWNLOAD_URL",
}
const applied = { outcome: "applied", item, error_code: null, detail: null }
const entry = (data: unknown, overrides = {}) => ({
  provider_key: "sharepoint",
  external_id: "private-drive",
  display_name: "Operations library",
  status: "success",
  data,
  error_code: null,
  error_message: null,
  ...overrides,
})
const names = Object.keys(argsByName)

function render(
  node: ReactNode,
  client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } })
) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(ToolConversationContext, { value: "conversation" }, node)
    )
  )
}

function props(
  name: string,
  status: ToolActivity["status"] = "completed",
  result: unknown = { results: [entry(applied)] }
): ToolRowPresenterProps {
  return {
    activity: { id: "write", kind: "call", name, status, args: argsByName[name], result },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "sharepoint",
  }
}

function approval(name: string, edits = {}): ToolRowPresenterProps {
  const fields = Object.keys(argsByName[name] ?? {})
    .filter((key) => !key.startsWith("_"))
    .map((key): ToolUiField => ({
      key,
      label: key,
      format:
        key === "content"
          ? "multiline"
          : ["parent", "folder", "file"].includes(key)
            ? "entity"
            : "text",
      editable: !["file", "expected_version"].includes(key),
      secondary: ["folder", "parent"].includes(key),
      entity_kind: ["folder", "parent", "file"].includes(key) ? "sharepoint_drive_item" : null,
      min_rows: 0,
      options: [],
      placeholder: "",
    }))
  const controls: ToolApprovalDecisionControls = {
    decision: { decision: "pending", edits, message: "" },
    disabled: false,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
  return {
    ...props(name, "awaiting_approval"),
    approvalDecision: controls,
    ui: {
      icon: "sharepoint",
      running_label: "",
      completed_label: "",
      failed_label: "",
      approval_title: "",
      approval_prompt: "",
      approve_label: "",
      arg_fields: fields,
      result_fields: [],
    },
  }
}

describe("SharePoint write presenters", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  it.each([
    ["sharepoint_create_folder", "parent"],
    ["sharepoint_write_file", "folder"],
    ["sharepoint_update_file", "file"],
  ])("shows the scoped path and library for %s", (name, field) => {
    const target = field === "file" ? reference : folder
    const args = { ...argsByName[name], [field]: target }
    const context = approval(name)
    context.activity.args = args
    const client = new QueryClient()
    client.setQueryData(
      entityReferenceHydrationQueryOptions({
        conversationId: "conversation",
        toolName: name,
        fieldKey: field,
        dependentArgs: {},
        exactValues: [target],
      }).queryKey,
      {
        entity_kind: "sharepoint_drive_item",
        choices: [
          {
            identity: ["1", "sharepoint_drive_item", "private-drive", "private-item"],
            value: target,
            label: "Resolved destination",
            scope_label: "Resolved library",
            description: 'Folder\n/Reports/<img src=x onerror="alert(1)">',
          },
        ],
      }
    )
    const html = render(renderCustomToolCallRow(context), client)
    expect(html).toContain("Resolved library")
    expect(html).toContain("Resolved destination")
    expect(html).toContain("/Reports/&lt;img")
    expect(html).not.toContain("<img")
    expect(html.replace(/<input[^>]*>/g, "")).not.toMatch(
      /private-drive|private-item|Operations library|Looking up/
    )
  })

  it.each(names)("renders the %s approval with its library and destination", (name) => {
    const html = render(renderCustomToolCallRow(approval(name)))
    expect(html).toContain("Operations library")
    expect(html).toContain(
      name === "sharepoint_update_file" ? "Reports / report.txt" : "Library root"
    )
    if (name === "sharepoint_update_file")
      expect(html).toContain("SharePoint keeps the previous version")
    else expect(html).toContain("-name-edit")
    if (name !== "sharepoint_create_folder") expect(html).toContain("<textarea")
    expect(html).not.toMatch(/private-drive|private-resource|private-item/)
  })

  it.each([
    ["sharepoint_create_folder", "parent"],
    ["sharepoint_write_file", "folder"],
  ])("offers a destination picker for omitted and null %s roots", (name, field) => {
    for (const initial of [undefined, null]) {
      const context = approval(name)
      context.activity.args = { ...argsByName[name], [field]: initial }
      const html = render(renderCustomToolCallRow(context))
      expect(html).toContain(`+ Add ${field}`)
      expect(html).toContain("Library root")
    }
  })

  it("keeps an explicit clear edit when the original proposal names a folder", () => {
    const context = approval("sharepoint_write_file", { folder: null })
    context.activity.args = { ...argsByName["sharepoint_write_file"], folder }
    const html = render(renderCustomToolCallRow(context))
    expect(html).toContain("Library root")
    expect(html).toContain("+ Add folder")
    expect(html).not.toContain("Reports / Monthly")
  })

  it.each(names)("shows public item evidence for applied %s", (name) => {
    const html = render(renderCustomToolCallRow(props(name)))
    for (const text of ["Saved report.txt", "/Reports/Monthly", "1.0 KB", "Open in SharePoint"])
      expect(html).toContain(text)
    expect(html).toContain(`href="${item.web_url.content}"`)
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).not.toMatch(/private-|PRIVATE_|source_ref|praxis_untrusted/)
  })

  it.each([
    ["version_conflict", "The file changed in SharePoint. Read it again before replacing it."],
    ["name_exists", "A file with this name exists. Replace it or choose another name."],
    ["locked", "The item is locked. Try again after the lock is released."],
    ["quota_exceeded", "The library has no storage space left."],
    ["upload_session_expired", "The upload session expired."],
    ["invalid_range", "The upload range was rejected."],
    ["unsupported_type", "Choose a supported File type"],
    ["source_changed", "The workspace File changed after review"],
    ["source_unavailable", "The workspace File is unavailable"],
    ["type_mismatch", "Match the source File type"],
    ["empty_content", "Choose a File with content"],
    ["too_large", "The file exceeds the upload limit."],
    ["unknown_error", "Safe server recovery"],
  ])("explains %s inside both failure envelopes", (code, copy) => {
    for (const result of [
      entry({ outcome: "failed", item: null, error_code: code, detail: "Safe server recovery" }),
      entry(null, { status: "error", error_code: code, error_message: "Safe server recovery" }),
    ]) {
      const html = render(
        renderCustomToolCallRow(props("sharepoint_write_file", "completed", { results: [result] }))
      )
      expect(html).toContain(copy)
      expect(html).toContain("Failed")
    }
  })

  it.each([
    entry({ ...applied, outcome: "unverified", error_code: "unverified_mutation" }),
    entry(
      { ...applied, outcome: "unverified" },
      { status: "error", error_code: "unverified_mutation" }
    ),
    entry(null, { status: "error", error_code: "unverified_mutation" }),
  ])("keeps uncertain writes unconfirmed", (result) => {
    const html = render(
      renderCustomToolCallRow(props("sharepoint_write_file", "completed", { results: [result] }))
    )
    expect(html).toContain("Unconfirmed")
    expect(html).toContain("Check the library in SharePoint before trying again.")
    expect(html).not.toContain("Success")
  })

  it.each([
    "javascript:alert(1)",
    "data:text/html,test",
    "file:///etc/passwd",
    "//example.com/file",
  ])("omits unsafe citation %s", (url) => {
    const html = render(
      renderCustomToolCallRow(
        props("sharepoint_write_file", "completed", {
          results: [entry({ ...applied, item: { ...item, web_url: node(url) } })],
        })
      )
    )
    expect(html).toContain("Saved report.txt")
    expect(html).not.toContain("Open in SharePoint")
    expect(html).not.toContain(url)
  })

  it("escapes provider names, paths, library names, and approved HTML and Markdown", () => {
    const hostile = '<img src=x onerror="alert(1)"> **bold** [link](javascript:alert(1))'
    const context = approval("sharepoint_write_file", { content: hostile })
    context.activity.args = { ...argsByName["sharepoint_write_file"], _library: hostile }
    const html =
      render(renderCustomToolCallRow(context)) +
      render(
        renderCustomToolCallRow(
          props("sharepoint_write_file", "completed", {
            results: [
              entry({ ...applied, item: { ...item, name: node(hostile), path: node(hostile) } }),
            ],
          })
        )
      )
    expect(html).toContain("&lt;img")
    expect(html).toContain("**bold**")
    expect(html).not.toMatch(/<img|<strong|<iframe|href="javascript:/)
    expect(html).not.toContain("PRIVATE_")
  })

  it.each([
    null,
    {},
    { outcome: "other" },
    { ...applied, item: null },
    { ...applied, detail: {} },
    { ...applied, item: { ...item, size_bytes: -1 } },
    { ...applied, item: { ...item, name: {} } },
    { ...applied, item: { ...item, path: null } },
    { ...applied, error_code: [] },
  ])("falls back for malformed result %j", (data) => {
    expect(
      renderCustomToolCallRow(
        props("sharepoint_write_file", "completed", { results: [entry(data)] })
      )
    ).toBeNull()
  })

  it.each(["running", "awaiting_approval", "denied", "failed", "unknown"] as const)(
    "renders lifecycle %s",
    (status) => {
      const html = render(renderCustomToolCallRow(props("sharepoint_write_file", status)))
      expect(html).toContain("SharePoint")
      if (status === "denied") expect(html).toContain("Declined")
      if (status === "unknown") expect(html).toContain("Unconfirmed")
    }
  )

  it.each([
    ["", "Enter a name"],
    ["a".repeat(256), "Enter a name"],
    [" leading", "leading or trailing"],
    ["trailing.", "leading or trailing"],
    ["~$temp", "~$ prefix"],
    ["a/b", "character SharePoint"],
    ["a\\b", "character SharePoint"],
    ["a:b", "character SharePoint"],
    ["bad\u0001", "character SharePoint"],
    ["CON.txt", "reserves this name"],
    ["Lpt9.csv", "reserves this name"],
    ["desktop.ini", "reserves this name"],
    ["deſktop.ini", "reserves this name"],
    ["desKtop.ini", "reserves this name"],
    ["a_vti_b", "reserves this name"],
    ["bad\ud800", "valid Unicode name"],
  ])("blocks an edited name %j with a reason", (name, reason) => {
    const html = render(renderCustomToolCallRow(approval("sharepoint_write_file", { name })))
    expect(html).toContain(reason)
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Approve/)
  })

  it.each(["sharepoint_write_file", "sharepoint_update_file"])(
    "blocks empty content in %s",
    (name) => {
      const html = render(renderCustomToolCallRow(approval(name, { content: "" })))
      expect(html).toContain("Enter content before saving the file.")
      expect(html).toMatch(/<button[^>]*disabled[^>]*>Approve/)
    }
  )

  it("validates text and folder kinds without rendering their content", () => {
    for (const [edits, reason] of [
      [{ content: "bad\u0001" }, "control characters"],
      [{ content: "bad\ud800" }, "valid Unicode"],
      [{ folder: reference }, "Choose a folder"],
    ] as const) {
      expect(
        validateSharePointWriteArgs(
          sharePointWriteFileArgs({ ...argsByName["sharepoint_write_file"], ...edits })
        )
      ).toContain(reason)
    }
    expect(
      validateSharePointWriteArgs(
        sharePointWriteFileArgs({
          ...argsByName["sharepoint_write_file"],
          name: "😀.txt",
          content: "\n\t😀",
        })
      )
    ).toBeNull()
  })

  it("edits name and multiline content through the shared editor and preserves replay", () => {
    vi.mocked(Input).mockClear()
    vi.mocked(Textarea).mockClear()
    const context = approval("sharepoint_write_file")
    render(renderCustomToolCallRow(context))
    vi.mocked(Input)
      .mock.calls.find(([props]) => props.id?.endsWith("-name-edit"))?.[0]
      .onChange?.({ currentTarget: { value: "renamed.txt" } } as ChangeEvent<HTMLInputElement>)
    vi.mocked(Textarea)
      .mock.calls.find(([props]) => props.id?.endsWith("-content-edit"))?.[0]
      .onChange?.({
        currentTarget: { value: "# Edited\n<b>text</b>" },
      } as ChangeEvent<HTMLTextAreaElement>)
    expect(context.approvalDecision?.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { name: "renamed.txt" },
      message: "",
    })
    expect(context.approvalDecision?.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { content: "# Edited\n<b>text</b>" },
      message: "",
    })
    const replay = { name: "report.txt", content: "Reviewed text", folder: null }
    expect(
      buildResumeDecisions(
        [
          {
            tool_call_id: "write",
            name: "sharepoint_write_file",
            args: argsByName["sharepoint_write_file"],
            replay_args: replay,
          },
        ],
        {
          write: {
            decision: "approved",
            edits: { name: "renamed.txt", content: "Edited" },
            message: "",
          },
        }
      )
    ).toEqual([
      {
        tool_call_id: "write",
        decision: "approved",
        override_args: { ...replay, name: "renamed.txt", content: "Edited" },
      },
    ])
  })

  it.each([
    ["sharepoint_create_folder", "parent"],
    ["sharepoint_write_file", "folder"],
  ])("edits the %s destination without retaining a stale library label", (name, field) => {
    vi.mocked(EntityFieldInput).mockClear()
    const context = approval(name)
    context.activity.args = { ...argsByName[name], [field]: folder }
    render(renderCustomToolCallRow(context))
    const edited = { ...folder, drive_id: "other-drive", label: "Other library / Reports" }
    vi.mocked(EntityFieldInput)
      .mock.calls.find(([props]) => props.field.key === field)?.[0]
      .onChange(edited)
    expect(context.approvalDecision?.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { [field]: edited },
      message: "",
    })
    const updated = render(renderCustomToolCallRow(approval(name, { [field]: edited })))
    expect(updated).toContain("Other library / Reports")
    expect(updated).not.toContain("Operations library")
    expect(updated).not.toContain("other-drive")
  })
})
