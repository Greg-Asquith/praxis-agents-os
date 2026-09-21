import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ToolApprovalCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolUiApprovalPrompt } from "@/features/conversations/tool-ui"
import type { PendingToolApproval } from "@/features/conversations/types"
import type { ToolUi } from "@/features/tools/types"

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

  it.each(["parent", "folder"])(
    "keeps a cross-library %s edit separate from default display metadata",
    (field) => {
      const replayArgs = { name: "Report", [field]: null }
      const approval: PendingToolApproval = {
        tool_call_id: "write",
        name: field === "parent" ? "sharepoint_create_folder" : "sharepoint_write_file",
        args: { ...replayArgs, _library: "Original library", _target: target },
        replay_args: replayArgs,
      }
      const editedFolder = {
        version: 1,
        entity_kind: "sharepoint_drive_item",
        label: "Edited library / Reports",
        drive_id: "edited-drive",
        item_id: "edited-parent",
        kind: "folder",
      }
      expect(
        buildResumeDecisions([approval], {
          write: { decision: "approved", edits: { [field]: editedFolder }, message: "" },
        })
      ).toEqual([
        {
          tool_call_id: "write",
          decision: "approved",
          override_args: { ...replayArgs, [field]: editedFolder },
        },
      ])
    }
  )

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
