import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ToolApprovalCard, type ApprovalField } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolUiApprovalPrompt } from "@/features/conversations/tool-ui"
import type { PendingToolApproval } from "@/features/conversations/types"
import type { ToolUi } from "@/features/tools/types"

const folderReference = {
  version: 1 as const,
  entity_kind: "sharepoint_drive_item",
  label: "Edited library / Reports",
  drive_id: "edited-drive",
  item_id: "edited-parent",
  kind: "folder",
}

function destinationField(key: string): ApprovalField {
  return {
    key,
    label: "Folder",
    format: "entity",
    editable: true,
    secondary: true,
    min_rows: 1,
    options: [],
    placeholder: "",
    entity_kind: "sharepoint_drive_item",
  }
}

const prompts = [
  "Create this folder. If no parent folder is chosen, use the root of SharePoint library {_library}. Existing folders and files are kept.",
  "Save this text as a new file. If no folder is chosen, use the root of SharePoint library {_library}. No existing file is replaced.",
  "Replace this file in SharePoint library {_library} with the reviewed text. A changed version stops the replacement.",
]

function approvalUi(prompt: string): ToolUi {
  return {
    icon: "sharepoint",
    running_label: "Saving",
    completed_label: "Saved",
    failed_label: "Could not save",
    approval_title: "Save to SharePoint",
    approval_prompt: prompt,
    approve_label: "Save",
    arg_fields: [],
    result_fields: [],
  }
}

const target = {
  drive_id: "private-drive",
  resource_id: "private-resource",
  connection_id: "private-connection",
}

describe("SharePoint write approval display", () => {
  it.each(prompts)("renders library metadata as text in %s", (template) => {
    const label = '<img src=x onerror="alert(1)"> [Library](javascript:alert(1)) {_target}'
    const args = { name: "Report", _library: label, _target: target }
    const activity = {
      id: "write",
      kind: "approval",
      name: "sharepoint_write_file",
      status: "awaiting_approval",
      args,
    } satisfies ToolActivity
    const prompt = toolUiApprovalPrompt(approvalUi(template), activity)
    expect(prompt).toBe(template.replace("{_library}", label))
    const html = renderToStaticMarkup(
      createElement(ToolApprovalCard, {
        title: "Save to SharePoint",
        prompt: prompt ?? "",
        decision: "pending",
        children: null,
        footer: null,
      })
    )
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
    expect(html).toContain("[Library](javascript:alert(1)) {_target}")
    expect(html).not.toContain("<img")
    expect(html).not.toContain("<a ")
    expect(html).not.toContain("private-")
    expect(approvalFallbackFields(args, [{ key: "name" }])).toEqual([])
  })

  it.each(["_library", "_target"])("rejects injected edits to %s", (key) => {
    const approval: PendingToolApproval = {
      tool_call_id: "write",
      name: "sharepoint_create_folder",
      args: { name: "Report", _library: "Documents", _target: target },
      replay_args: { name: "Report" },
    }
    expect(
      buildResumeDecisions([approval], {
        write: { decision: "approved", edits: { [key]: "injected" }, message: "" },
      })
    ).toBe("This request can no longer be edited. Refresh and try again.")
  })
})

describe.each(["parent", "folder"])("SharePoint %s destination replay", (field) => {
  describe.each(["direct", "nested"])("%s approval path", (path) => {
    const identity = path === "nested" ? { approval_id: "nested-write" } : {}
    const key = identity.approval_id ?? "write"

    it.each(["omitted", "null"])("selects another library from an %s root", (initial) => {
      const replayArgs = { name: "Report", ...(initial === "null" ? { [field]: null } : {}) }
      const approval: PendingToolApproval = {
        ...identity,
        tool_call_id: "write",
        name: field === "parent" ? "sharepoint_create_folder" : "sharepoint_write_file",
        args: { ...replayArgs, _library: "Original library", _target: target },
        replay_args: replayArgs,
      }
      expect(
        buildResumeDecisions(
          [approval],
          { [key]: { decision: "approved", edits: { [field]: folderReference }, message: "" } },
          () => [destinationField(field)]
        )
      ).toEqual([
        {
          ...identity,
          tool_call_id: "write",
          decision: "approved",
          override_args: { ...replayArgs, [field]: folderReference },
        },
      ])
    })

    it("submits an explicit root edit with executable arguments only", () => {
      const replayArgs = { name: "Report", [field]: folderReference }
      const approval: PendingToolApproval = {
        ...identity,
        tool_call_id: "write",
        name: field === "parent" ? "sharepoint_create_folder" : "sharepoint_write_file",
        args: { ...replayArgs, _library: "Edited library", _target: target },
        replay_args: replayArgs,
      }
      expect(
        buildResumeDecisions(
          [approval],
          { [key]: { decision: "approved", edits: { [field]: null }, message: "" } },
          () => [destinationField(field)]
        )
      ).toEqual([
        {
          ...identity,
          tool_call_id: "write",
          decision: "approved",
          override_args: { name: "Report", [field]: null },
        },
      ])
    })

    it.each([null, { ...folderReference, item_id: "replacement-file", kind: "file" }])(
      "rejects clearing or replacing a locked file target %j",
      (file) => {
        const originalFile = { ...folderReference, item_id: "original-file", kind: "file" }
        expect(
          buildResumeDecisions(
            [
              {
                ...identity,
                tool_call_id: "write",
                name: "sharepoint_update_file",
                args: { file: originalFile },
              },
            ],
            { [key]: { decision: "approved", edits: { file }, message: "" } },
            () => [{ ...destinationField("file"), editable: false, secondary: false }]
          )
        ).toBe("This request can no longer be edited. Refresh and try again.")
      }
    )
  })
})
