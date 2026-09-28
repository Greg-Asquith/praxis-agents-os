import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { entityReferenceHydrationQueryOptions } from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { PendingToolApproval } from "@/features/conversations/types"
import type { EntityChoice, ToolUi, ToolUiField } from "@/features/tools/types"
import { notionWritePresenter } from "@/integrations/notion/presenters/write"
import { isRecord } from "@/lib/guards"
import { approvalIdentity } from "../../support/approvals"

const page = {
  version: 1,
  entity_kind: "notion_page",
  workspace_id: "workspace-1",
  page_id: "page-1",
  label: "Launch plan",
  description: "Notion page",
  scope_label: "Operations workspace",
}

const propertyColumns = [
  column("name", "Property", [], true),
  column(
    "type",
    "Type",
    [
      "title",
      "rich_text",
      "number",
      "checkbox",
      "url",
      "email",
      "phone_number",
      "date",
      "select",
      "status",
      "multi_select",
    ],
    true
  ),
  column("value", "Value"),
]

const replacementColumns = [
  column("old_text", "Find", [], true),
  column("new_text", "Replace with"),
  column("replace_all", "Replace all", ["no", "yes"], true),
]

const writeUi: Record<string, ToolUi> = {
  notion_create_page: ui("Create Notion Page", "Approve & Create", [
    entityField("parent_page", "Parent Page", "notion_page", true),
    entityField("parent_data_source", "Parent Data Source", "notion_data_source", true),
    field("title", "Title", "text", true),
    field("content_md", "Content", "markdown", true, true),
    recordsField("properties", "Properties", propertyColumns, 0, true),
  ]),
  notion_update_page_content: ui("Update Notion Page Content", "Approve & Update", [
    entityField("page", "Page", "notion_page"),
    recordsField("replacements", "Replacements", replacementColumns, 1),
  ]),
  notion_update_page_properties: ui("Update Notion Page Properties", "Approve & Update", [
    entityField("page", "Page", "notion_page"),
    recordsField("properties", "Properties", propertyColumns, 1),
  ]),
}

describe("Notion write approval and result fidelity", () => {
  it("shows every non-null create argument and keeps the unused parent null in the approved payload", () => {
    const args = {
      parent_page: page,
      parent_data_source: null,
      title: "Launch notes",
      content_md: "# Draft\nKeep this exact Markdown.",
      properties: [{ name: "Status", type: "status", value: "Draft" }],
    }
    const edits = {
      title: "Approved launch notes",
      content_md: "# Approved\nKeep this exact Markdown.",
      properties: [{ name: "Status", type: "status", value: "Ready" }],
    }
    const approval: PendingToolApproval = {
      ...approvalIdentity("notion-create-1"),
      tool_call_id: "notion-create-1",
      name: "notion_create_page",
      args,
    }

    expect(
      buildResumeDecisions(
        [approval],
        {
          "notion-create-1": { decision: "approved", edits, message: "" },
        },
        (toolName) => writeUi[toolName]?.arg_fields
      )
    ).toEqual([
      {
        decision: "approved",
        override_args: { ...args, ...edits },
        approval_id: "notion-create-1",
        tool_call_id: "notion-create-1",
      },
    ])

    const html = renderPresenter(
      activity("notion_create_page", "awaiting_approval", args),
      controls({ decision: "approved", edits, message: "" })
    )
    expect(html).toContain("Approved launch notes")
    expect(html).not.toContain("Launch tracker")
    expect(html).not.toContain("Launch notes</")
    expect(html).not.toContain("# Draft")
  })

  it("shows the external-data warning and its source before approval", () => {
    const pending = activity("notion_update_page_properties", "awaiting_approval", {
      page,
      properties: [{ name: "Status", type: "status", value: "Ready" }],
    })
    pending.derivedFromUntrusted = true
    pending.taintSources = [{ source_kind: "notion_page", source_ref: "source-page-1" }]

    const html = renderPresenter(pending, pendingControls())

    expect(html).toContain("Based on external data")
    expect(html).toContain("source-page-1")
  })

  it.each([
    [
      "notion_update_page_content",
      {
        outcome: "applied",
        error_code: null,
        reference: page,
        applied_replacements: 0,
        page_truncated: null,
        last_edited_time: null,
      },
    ],
  ])("fails closed for malformed applied results from %s", (name, data) => {
    const html = renderPresenter(resultActivity(name, fanOut(data), { page }))

    expect(html).toContain("The system couldn&#x27;t confirm the page")
    expect(html).toContain("Unconfirmed")
    expect(html).not.toContain("Change confirmed")
  })
})

function renderPresenter(
  toolActivity: ToolActivity,
  approvalDecision?: ToolApprovalDecisionControls,
  live = false
) {
  const uiDefinition = writeUi[toolActivity.name]
  if (!uiDefinition) {
    throw new Error(`Missing test presentation for ${toolActivity.name}`)
  }
  const node = notionWritePresenter.render({
    activity: toolActivity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    label: uiDefinition.approval_title,
    live,
    providerKey: "notion",
    ui: uiDefinition,
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  seedEntityHydration(queryClient, toolActivity, uiDefinition, approvalDecision)
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(ToolConversationContext, {
        value: "conversation-1",
        children: node,
      }),
    })
  )
}

function seedEntityHydration(
  queryClient: QueryClient,
  toolActivity: ToolActivity,
  uiDefinition: ToolUi,
  approvalDecision?: ToolApprovalDecisionControls
) {
  const dependentArgs = mergeApprovalArgs(toolActivity.args, approvalDecision?.decision.edits ?? {})
  if (!isRecord(dependentArgs)) {
    return
  }
  for (const approvalField of uiDefinition.arg_fields) {
    const candidate = dependentArgs[approvalField.key]
    if (approvalField.format !== "entity" || !isRecord(candidate)) {
      continue
    }
    const value = candidate
    const entityKind = approvalField.entity_kind ?? "notion_target"
    const choice: EntityChoice = {
      identity: ["1", entityKind, approvalField.key],
      value,
      label: typeof value["label"] === "string" ? value["label"] : "Notion target",
      description: typeof value["description"] === "string" ? value["description"] : null,
      scope_label: typeof value["scope_label"] === "string" ? value["scope_label"] : null,
    }
    const request = {
      conversationId: "conversation-1",
      dependentArgs,
      exactValues: [value],
      fieldKey: approvalField.key,
      toolName: toolActivity.name,
    }
    queryClient.setQueryData(entityReferenceHydrationQueryOptions(request).queryKey, {
      entity_kind: entityKind,
      choices: [choice],
    })
  }
}

function activity(name: string, status: ToolActivity["status"], args: unknown): ToolActivity {
  return { id: `${name}-1`, kind: "call", name, status, args }
}

function resultActivity(name: string, result: unknown, args: unknown): ToolActivity {
  return { id: `${name}-result-1`, kind: "result", name, status: "completed", args, result }
}

function fanOut(data: unknown) {
  return {
    results: [
      {
        provider_key: "notion",
        external_id: "workspace-1",
        display_name: "Operations workspace",
        status: "success",
        data,
        error_code: null,
        error_message: null,
      },
    ],
  }
}

function pendingControls() {
  return controls({ decision: "pending", edits: {}, message: "" })
}

function controls(
  decision: ToolApprovalDecisionControls["decision"]
): ToolApprovalDecisionControls {
  return {
    decision,
    disabled: false,
    error: null,
    onDecisionChange: () => undefined,
    onRetry: () => undefined,
    pendingCount: decision.decision === "pending" ? 1 : 0,
    submitting: false,
  }
}

function ui(title: string, approveLabel: string, argFields: ToolUiField[]): ToolUi {
  return {
    icon: "notion",
    running_label: title,
    completed_label: title,
    failed_label: `Couldn't ${title}`,
    approval_title: title,
    approval_prompt: "Review this Notion change.",
    approve_label: approveLabel,
    arg_fields: argFields,
    result_fields: [field("results", "Workspaces", "list")],
  }
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"],
  editable = false,
  secondary = false
): ToolUiField {
  return { key, label, min_rows: 0, format, editable, placeholder: "", options: [], secondary }
}

function entityField(
  key: string,
  label: string,
  entityKind: string,
  secondary = false
): ToolUiField {
  return { ...field(key, label, "entity", true, secondary), entity_kind: entityKind }
}

function recordsField(
  key: string,
  label: string,
  columns: NonNullable<ToolUiField["columns"]>,
  minRows: number,
  secondary = false
): ToolUiField {
  return {
    ...field(key, label, "records", true, secondary),
    columns,
    min_rows: minRows,
  }
}

function column(key: string, label: string, options: string[] = [], required = false) {
  return { key, label, options, placeholder: "", required }
}
