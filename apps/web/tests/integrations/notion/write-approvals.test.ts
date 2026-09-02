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
import { resolveUiFields } from "@/features/conversations/tool-ui"
import type { EntityChoice, ToolUi, ToolUiField } from "@/features/tools/types"
import { notionWritePresenter } from "@/integrations/notion/presenters/write"
import { isRecord } from "@/lib/guards"

const page = {
  version: 1,
  entity_kind: "notion_page",
  workspace_id: "workspace-1",
  page_id: "page-1",
  label: "Launch plan",
  description: "Notion page",
  scope_label: "Operations workspace",
}

const dataSource = {
  version: 1,
  entity_kind: "notion_data_source",
  workspace_id: "workspace-1",
  data_source_id: "source-1",
  label: "Launch tracker",
  description: "Notion data source",
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
  it("renders every replacement and property cell through the server-declared records schema", () => {
    const contentHtml = renderPresenter(
      activity("notion_update_page_content", "awaiting_approval", {
        page,
        replacements: [
          { old_text: "Draft", new_text: "Approved", replace_all: "no" },
          { old_text: "2025", new_text: "2026", replace_all: "yes" },
        ],
      }),
      pendingControls()
    )
    expect(contentHtml).toContain('value="Launch plan"')
    expect(contentHtml).toContain("Find")
    expect(contentHtml).toContain("Replace with")
    expect(contentHtml).toContain("Replace all")
    expect(contentHtml).toContain('value="Draft"')
    expect(contentHtml).toContain('value="Approved"')
    expect(contentHtml).toContain(">No<")
    expect(contentHtml).toContain(">Yes<")

    const propertiesHtml = renderPresenter(
      activity("notion_update_page_properties", "awaiting_approval", {
        page,
        properties: [
          { name: "Estimate", type: "number", value: "12.50" },
          { name: "Status", type: "status", value: "Ready" },
        ],
      }),
      pendingControls()
    )
    expect(propertiesHtml).toContain("Property")
    expect(propertiesHtml).toContain("Type")
    expect(propertiesHtml).toContain("Value")
    expect(propertiesHtml).toContain('value="Estimate"')
    expect(propertiesHtml).toContain('value="12.50"')
    expect(propertiesHtml).toContain(">Number<")
    expect(propertiesHtml).toContain(">Status<")
    expect(propertiesHtml).not.toContain('type="number"')
  })

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
        tool_call_id: "notion-create-1",
      },
    ])

    const html = renderPresenter(
      activity("notion_create_page", "awaiting_approval", args),
      controls({ decision: "approved", edits, message: "" })
    )
    expect(html).toContain("Approved")
    expect(html).toContain("Launch plan")
    expect(html).toContain("Approved launch notes")
    expect(html).toContain("# Approved")
    expect(html).toContain("Ready")
    expect(html).not.toContain("Launch tracker")
    expect(html).not.toContain("Launch notes</")
    expect(html).not.toContain("# Draft")
  })

  it("uses the same presenter for live progress, pending consent, denial, and failure", () => {
    const args = {
      page,
      replacements: [{ old_text: "Draft", new_text: "Final", replace_all: "no" }],
    }

    expect(
      renderPresenter(activity("notion_update_page_content", "running", args), undefined, true)
    ).toContain("Updating Notion page content…")
    expect(
      renderPresenter(activity("notion_update_page_content", "awaiting_approval", args))
    ).toContain("Waiting for page content approval…")
    expect(
      renderPresenter(
        activity("notion_update_page_content", "awaiting_approval", args),
        pendingControls()
      )
    ).toContain("Requires Approval")
    const denied = activity("notion_update_page_content", "denied", args)
    denied.decisionReason = "Keep the draft wording."
    const deniedHtml = renderPresenter(denied)
    expect(deniedHtml).toContain("This Notion change was declined. Nothing was changed.")
    expect(deniedHtml).toContain("Declined")
    expect(deniedHtml).toContain("Keep the draft wording.")
    expect(deniedHtml).not.toContain("Failed")
    expect(renderPresenter(activity("notion_update_page_content", "failed", args))).toContain(
      "The Notion change did not finish. No change was confirmed."
    )
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

  it("renders persisted success receipts after the declarative result field loses fan-out structure", () => {
    const createResult = fanOut({
      outcome: "applied",
      error_code: null,
      reference: { ...page, page_id: "page-2", label: "Approved launch notes" },
      url: "https://www.notion.so/page-2",
      title: "Approved launch notes",
      last_edited_time: "2026-09-01T12:00:00Z",
    })
    expect(
      resolveUiFields(writeUi["notion_create_page"]?.result_fields ?? [], createResult)
    ).toEqual([])
    const createHtml = renderPresenter(
      resultActivity("notion_create_page", createResult, { parent_data_source: dataSource })
    )
    expect(createHtml).toContain("Change confirmed")
    expect(createHtml).toContain("Approved launch notes")
    expect(createHtml).toContain("https://www.notion.so/page-2")

    const contentHtml = renderPresenter(
      resultActivity(
        "notion_update_page_content",
        fanOut({
          outcome: "applied",
          error_code: null,
          reference: page,
          applied_replacements: 2,
          page_truncated: true,
          last_edited_time: "2026-09-01T12:00:00Z",
        }),
        { page }
      )
    )
    expect(contentHtml).toContain("Applied 2 exact-text replacements.")
    expect(contentHtml).toContain("Notion response truncated")

    const contentWithoutTimestampHtml = renderPresenter(
      resultActivity(
        "notion_update_page_content",
        fanOut({
          outcome: "applied",
          error_code: null,
          reference: page,
          applied_replacements: 1,
          page_truncated: false,
          last_edited_time: null,
        }),
        { page }
      )
    )
    expect(contentWithoutTimestampHtml).toContain("Change confirmed")
    expect(contentWithoutTimestampHtml).toContain("Applied 1 exact-text replacement.")
    expect(contentWithoutTimestampHtml).not.toContain("Last edited")

    const propertiesHtml = renderPresenter(
      resultActivity(
        "notion_update_page_properties",
        fanOut({
          outcome: "applied",
          error_code: null,
          reference: page,
          url: "https://www.notion.so/page-1",
          last_edited_time: "2026-09-01T12:00:00Z",
        }),
        { page }
      )
    )
    expect(propertiesHtml).toContain("Updated the selected page properties.")
    expect(propertiesHtml).toContain("Launch plan")
  })

  it("renders provider failure and unverified mutation entries as non-success outcomes", () => {
    const failedHtml = renderPresenter(
      resultActivity(
        "notion_update_page_properties",
        fanOutError("validation_error", "The selected Notion properties were not accepted."),
        { page }
      )
    )
    expect(failedHtml).toContain("The selected Notion properties were not accepted.")
    expect(failedHtml).toContain("Failed")
    expect(failedHtml).not.toContain("Change confirmed")

    const unverifiedHtml = renderPresenter(
      resultActivity(
        "notion_update_page_properties",
        fanOutError(
          "unverified_mutation",
          "The provider mutation outcome could not be verified exactly.",
          { outcome: "unverified", error_code: "timeout", reference: page }
        ),
        { page }
      )
    )
    expect(unverifiedHtml).toContain("couldn&#x27;t verify whether Notion applied this change")
    expect(unverifiedHtml).toContain("Check the page in Notion before taking further action.")
    expect(unverifiedHtml).toContain("Failed")
    expect(unverifiedHtml).not.toContain("Change confirmed")
    expect(unverifiedHtml).not.toContain("timeout")
  })

  it.each([
    [
      "notion_create_page",
      {
        outcome: "applied",
        error_code: null,
        reference: null,
        url: null,
        title: "Launch notes",
        last_edited_time: null,
      },
    ],
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
    [
      "notion_update_page_properties",
      {
        outcome: "applied",
        error_code: null,
        reference: page,
        url: null,
        last_edited_time: null,
      },
    ],
  ])("fails closed for malformed applied results from %s", (name, data) => {
    const html = renderPresenter(resultActivity(name, fanOut(data), { page }))

    expect(html).toContain("Praxis could not confirm the Notion change.")
    expect(html).toContain("Failed")
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

function fanOutError(errorCode: string, errorMessage: string, data: unknown = null) {
  return {
    results: [
      {
        provider_key: "notion",
        external_id: "workspace-1",
        display_name: "Operations workspace",
        status: "error",
        data,
        error_code: errorCode,
        error_message: errorMessage,
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
