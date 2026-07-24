import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import {
  DelegateAgentListRow,
  DelegationToolRow,
} from "@/features/conversations/components/delegation-tool-row"
import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { skillsQueryOptions } from "@/features/skills/api/list-skills"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"

describe("delegation tool rows", () => {
  it("renders available agents through a result card and a running skeleton", () => {
    const completed = render(
      createElement(DelegateAgentListRow, {
        activity: activity({
          name: "list_delegate_agents",
          result: [
            { id: "agent-1", name: "Research Agent", description: "Checks source material." },
          ],
        }),
        defaultOpen: true,
      })
    )
    const running = render(
      createElement(DelegateAgentListRow, {
        activity: activity({ name: "list_delegate_agents", status: "running", result: undefined }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Available Agents")
    expect(completed).toContain("1 Agent")
    expect(completed).toContain("Research Agent")
    expect(completed).toContain("Checks source material.")
    expect(completed).toContain(">Details<")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(running).toContain('aria-busy="true"')
    expect(running).toContain("Finding available agents…")
  })

  it("renders completed and failed delegate outcomes with honest status copy", () => {
    const completed = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({
          output: "**The source review** is complete.",
          status: "completed",
        }),
        defaultOpen: true,
      })
    )
    const failed = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({
          error: "The delegated model could not finish.",
          status: "failed",
        }),
        defaultOpen: false,
      })
    )
    const denied = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "running" }),
          status: "denied",
        },
        defaultOpen: false,
      })
    )
    const running = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({ status: "running" }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Research Agent")
    expect(completed).toContain("Task")
    expect(completed).toContain("<strong")
    expect(completed).toContain("The source review</strong> is complete.")
    expect(completed).not.toContain("**The source review**")
    expect(completed).toContain("whitespace-normal")
    expect(completed).toContain(">Done<")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(failed).toContain("The delegated model could not finish.")
    expect(failed).toContain(">Failed<")
    expect(failed).toContain('aria-expanded="true"')
    expect(denied).toContain("This delegation was declined, so no work was started.")
    expect(denied).toContain(">Declined<")
    expect(denied).not.toContain("Delegating to Research Agent…")
    expect(running).toContain("Delegating to Research Agent…")
    expect(running).toContain('aria-busy="true"')
  })

  it("uses the shared approval card and preserves its controls contract", () => {
    const controls = approvalControls()
    const html = render(
      createElement(DelegationToolRow, {
        activity: delegationActivity({ status: "awaiting_approval" }),
        approvalDecision: controls,
        defaultOpen: false,
      })
    )

    expect(html).toContain("Delegate to Research Agent")
    expect(html).toContain("Approve &amp; Delegate")
    expect(html).toContain("Decline")
    expect(html).toContain("Review launch evidence")
    expect(html).toContain("Delegate to Agent")
    expect(controls.onDecisionChange).not.toHaveBeenCalled()
  })

  it("shows the delegated tool parameters in its approval card", () => {
    const controls = approvalControls()
    const html = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "awaiting_approval", taskPreview: null }),
          args: { dry_run: true, value: "external mutation" },
          kind: "approval",
          name: "delegated_external_write",
          status: "awaiting_approval",
        },
        approvalDecision: controls,
        defaultOpen: false,
      })
    )

    expect(html).toContain("Research Agent: External Write")
    expect(html).toContain("Review the parameters before approving.")
    expect(html).toContain("Value")
    expect(html).toContain("external mutation")
    expect(html).toContain("Dry Run")
    expect(html).toContain(">Yes<")
    expect(html).toContain(">Approve<")
    expect(html).not.toContain("Approve &amp; Delegate")
    expect(controls.onDecisionChange).not.toHaveBeenCalled()
  })

  it("falls back to readable parameters for delegated tools without presentation metadata", () => {
    const html = render(
      createElement(DelegationToolRow, {
        activity: {
          ...delegationActivity({ status: "awaiting_approval", taskPreview: null }),
          args: { attempts: 2, recipient: "ops@example.com" },
          kind: "approval",
          name: "custom_external_action",
          status: "awaiting_approval",
        },
        approvalDecision: approvalControls(),
        defaultOpen: false,
      })
    )

    expect(html).toContain("Tool")
    expect(html).toContain("custom_external_action")
    expect(html).toContain("Attempts")
    expect(html).toContain(">2<")
    expect(html).toContain("Recipient")
    expect(html).toContain("ops@example.com")
  })

  it("returns null for unexpected list and delegation shapes", () => {
    expect(
      render(
        createElement(DelegateAgentListRow, {
          activity: activity({ name: "list_delegate_agents", result: { agents: [] } }),
          defaultOpen: false,
        })
      )
    ).toBe("")
    expect(
      render(
        createElement(DelegationToolRow, {
          activity: activity({ name: "delegate_to_agent" }),
          defaultOpen: false,
        })
      )
    ).toBe("")
  })
})

describe("skill tool rows", () => {
  it("renders activation as a non-expandable heading-only card", () => {
    const html = render(
      createElement(SkillActivationRow, {
        activity: activity({
          args: { id: "skill:skill-1" },
          name: "load_capability",
          toolKind: "capability-load",
        }),
      }),
      { seedSkills: true }
    )

    expect(html).toContain("Activated Skill: Source Research")
    expect(html).toContain(">Done<")
    expect(html).not.toContain("Expand results")
    expect(html).not.toContain(">Details<")
  })

  it("renders skill documents, running state, errors, and malformed fallback", () => {
    const completed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          args: { document: "guide", skill: "research" },
          name: "read_skill_document",
          result:
            "<skill-document skill='research' document='guide'>\n# Guidance\nUse primary sources.\n</skill-document>",
        }),
        defaultOpen: true,
      })
    )
    const running = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          args: { document: "guide", skill: "research" },
          name: "read_skill_document",
          status: "running",
          result: undefined,
        }),
      })
    )
    const failed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({
          name: "read_skill_document",
          status: "failed",
          result: "The document is no longer available.",
        }),
        defaultOpen: true,
      })
    )
    const malformed = render(
      createElement(SkillDocumentReadRow, {
        activity: activity({ name: "read_skill_document", result: { content: "unexpected" } }),
      })
    )

    expect(completed).toContain("Read Skill Document")
    expect(completed).toContain("Guidance")
    expect(completed).toContain("Use primary sources.")
    expect(completed).not.toContain("&lt;skill-document")
    expect(completed).not.toContain('data-slot="tool-field-well"')
    expect(running).toContain("Reading skill document…")
    expect(running).toContain('aria-busy="true"')
    expect(failed).toContain("What Went Wrong")
    expect(failed).toContain("The document is no longer available.")
    expect(malformed).toBe("")
  })
})

describe("file tool rows", () => {
  it("renders file lists with details and preserves file entities", () => {
    const html = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "list_files",
          result: {
            files: [
              {
                id: "file-1",
                name: "brief.md",
                category: "editable_text",
                media_type: "text/markdown",
                size_bytes: 128,
                processing_status: "ready",
                updated_at: "2026-07-24T10:00:00Z",
              },
            ],
            scratch: [
              {
                name: "notes.md",
                content_bytes: 64,
                updated_at: "2026-07-24T09:00:00Z",
                expires_at: "2026-07-25T09:00:00Z",
              },
            ],
            total: 1,
          },
        }),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Workspace Files")
    expect(html).toContain("1 File")
    expect(html).toContain("brief.md")
    expect(html).toContain("notes.md")
    expect(html).toContain(">Details<")
    expect(html).toContain("Drafts: 1")
    expect(html).not.toContain("Kept until")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders running and failed file states without claiming success", () => {
    const running = render(
      createElement(FileToolRow, {
        activity: activity({ name: "read_file", status: "running", result: undefined }),
        defaultOpen: false,
      })
    )
    const failed = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "write_file",
          status: "failed",
          result: "Storage was unavailable.",
        }),
        defaultOpen: false,
      })
    )

    expect(running).toContain("Reading file…")
    expect(running).toContain('aria-busy="true"')
    expect(failed).toContain("Storage was unavailable.")
    expect(failed).toContain(">Failed<")
    expect(failed).not.toContain(">Done<")
  })

  it("renders content metadata in Details and falls through for malformed results", () => {
    const completed = render(
      createElement(FileToolRow, {
        activity: activity({
          name: "read_file",
          result: {
            mode: "content",
            content: "# Launch brief",
            end_offset: 14,
            file_id: "file-1",
            media_type: "text/markdown",
            name: "brief.md",
            offset: 0,
            total_bytes: 42,
            truncated: true,
          },
        }),
        defaultOpen: true,
      })
    )
    const malformed = render(
      createElement(FileToolRow, {
        activity: activity({ name: "read_file", result: { mode: "content" } }),
        defaultOpen: false,
      })
    )

    expect(completed).toContain("Content Read")
    expect(completed).toContain("0–14 bytes")
    expect(completed).toContain("This view is truncated. More content is available.")
    expect(completed).toContain("Launch brief")
    expect(malformed).toBe("")
  })
})

function render(element: ReactElement, options: { seedSkills?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, {
    tools: [
      {
        effect: "write",
        label: "External Write",
        name: "delegated_external_write",
        provider: "praxis",
        ui: {
          approval_prompt: "Approve the external write.",
          approval_title: "External Write",
          approve_label: "Approve",
          arg_fields: [
            {
              editable: false,
              format: "text",
              key: "value",
              label: "Value",
              options: [],
              placeholder: "",
              secondary: false,
            },
            {
              editable: false,
              format: "boolean",
              key: "dry_run",
              label: "Dry Run",
              options: [],
              placeholder: "",
              secondary: false,
            },
          ],
          completed_label: "Wrote",
          failed_label: "Write Failed",
          icon: "tool",
          result_fields: [],
          running_label: "Writing",
        },
      },
      {
        effect: "write",
        label: "Delegate to Agent",
        name: "delegate_to_agent",
        provider: "praxis",
        ui: {
          approval_prompt: "Delegate this task.",
          approval_title: "Delegate to Agent",
          approve_label: "Approve & Delegate",
          arg_fields: [],
          completed_label: "Delegated",
          failed_label: "Delegation Failed",
          icon: "bot",
          result_fields: [],
          running_label: "Delegating",
        },
      },
    ],
  })
  if (options.seedSkills) {
    queryClient.setQueryData(skillsQueryOptions({ includeInactive: true }).queryKey, {
      skills: [
        {
          id: "skill-1",
          name: "source-research",
          human_name: "Source Research",
          description: "Researches primary sources.",
          instructions: "Use primary sources.",
          workspace_id: "workspace-1",
          created_by: "user-1",
          documentation_refs: {},
          is_active: true,
          is_favorite: false,
          last_used_at: null,
          metadata: null,
          created_at: "2026-07-24T00:00:00Z",
          updated_at: "2026-07-24T00:00:00Z",
          deleted: false,
          deleted_at: null,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    })
  }
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient, children: element })
  )
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "tool-1",
    kind: "result",
    name: "tool",
    status: "completed",
    ...overrides,
  }
}

function delegationActivity(
  delegate: Partial<NonNullable<ToolActivity["delegate"]>>
): ToolActivity {
  return activity({
    args: { agent_id: "agent-1", task: "Review launch evidence" },
    name: "delegate_to_agent",
    status: delegate.status === "failed" ? "failed" : "completed",
    delegate: {
      agentId: "agent-1",
      agentName: "Research Agent",
      conversationId: null,
      error: null,
      output: null,
      pendingApprovalCount: 0,
      runId: "run-1",
      status: "completed",
      taskPreview: "Review launch evidence",
      truncated: false,
      ...delegate,
    },
  })
}

function approvalControls(): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    disabled: false,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}
