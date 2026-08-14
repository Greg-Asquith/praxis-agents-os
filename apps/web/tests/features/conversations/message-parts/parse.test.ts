import { describe, expect, it } from "vitest"

import {
  parseConversationMessages,
  toolActivityIdentity,
} from "@/features/conversations/message-parts"
import type {
  AgentRun,
  AgentRunStatus,
  ConversationMessage,
  PendingDelegatedApproval,
} from "@/features/conversations/types"

const createdAt = "2026-07-07T10:00:00.000Z"
const run = (id: string, status: AgentRunStatus): Pick<AgentRun, "id" | "status"> => ({
  id,
  status,
})

function message(
  id: string,
  role: string,
  sequence: number,
  parts: Record<string, unknown>[],
  metadata: Record<string, unknown> | null = null
): ConversationMessage {
  return {
    id,
    conversation_id: "conversation-1",
    role,
    parts: { parts },
    metadata,
    tool_name: null,
    error: null,
    sequence,
    client_message_id: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

describe("parseConversationMessages", () => {
  it("marks an unresolved tool call as failed when its run failed", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "send-1",
              tool_name: "gmail_send_message",
              args: { to: ["client@example.com"], subject: "Update", body_html: "<p>Hello</p>" },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "failed")
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "send-1",
      status: "failed",
    })
  })

  it("hides internal tool validation retries from the user-facing transcript", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_name: "google_ads_add_negative_keywords",
          args: { negative_list: { entity_id: "50" } },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "retry-prompt",
          tool_call_id: "tool-call-1",
          tool_name: "google_ads_add_negative_keywords",
          content: [{ msg: "Extra inputs are not permitted" }],
        },
      ]),
    ])

    expect(parsed).toEqual([])
  })

  it("preserves thinking and visible parts in source order", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        { part_kind: "thinking", content: "Hidden reasoning" },
        { part_kind: "text", content: "First, I will check." },
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_name: "web_search",
          args: { query: "Praxis Agents" },
        },
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "web_search",
          outcome: "success",
          content: { answer: "Found it" },
        },
        { part_kind: "text", content: "Here is the conclusion." },
      ]),
    ])

    expect(parsed[0]?.parts).toMatchObject([
      { kind: "thinking", content: "Hidden reasoning" },
      { kind: "text", content: "First, I will check." },
      { kind: "tool", activity: { id: "tool-call-1", status: "completed" } },
      { kind: "text", content: "Here is the conclusion." },
    ])
  })

  it("marks messages without an ordered parts array for grouped fallback rendering", () => {
    const fallbackMessage = message("message-1", "assistant", 1, [])
    fallbackMessage.parts = { content: "Legacy answer" }

    const parsed = parseConversationMessages([fallbackMessage])

    expect(parsed[0]).toMatchObject({ parts: null, text: ["Legacy answer"] })
  })

  it("parses a plain user and assistant exchange", () => {
    const parsed = parseConversationMessages([
      message("message-1", "user", 1, [{ part_kind: "user-prompt", content: "Hello" }]),
      message("message-2", "assistant", 2, [{ part_kind: "text", content: "How can I help?" }]),
    ])

    expect(parsed).toHaveLength(2)
    expect(parsed[0]).toMatchObject({
      id: "message-1",
      role: "user",
      sequence: 1,
      text: ["Hello"],
      toolActivities: [],
      unsupportedParts: [],
    })
    expect(parsed[1]).toMatchObject({
      id: "message-2",
      role: "assistant",
      sequence: 2,
      text: ["How can I help?"],
      toolActivities: [],
      unsupportedParts: [],
    })
  })

  it("pairs a tool call with its result and removes the standalone result row", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_name: "read_file",
          args: { file_id: "file-1" },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "read_file",
          outcome: "success",
          content: { text: "File contents" },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities).toEqual([
      {
        id: "tool-call-1",
        agentRunId: null,
        kind: "call",
        status: "completed",
        name: "read_file",
        args: { file_id: "file-1" },
        outcome: "success",
        result: { text: "File contents" },
      },
    ])
  })

  it("rebuilds a workflow tree only from persisted nested-trace metadata", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "workflow-1",
          tool_name: "run_workflow",
          args: {
            code: "report = await google_ads_run_report(query='campaigns')\nreport",
            reason: "Find weak campaigns",
          },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "workflow-1",
          tool_name: "run_workflow",
          outcome: "success",
          content: { result: "done" },
          metadata: {
            code_mode_trace: {
              calls: [
                {
                  order: 1,
                  tool_call_id: "workflow-1:1",
                  parent_tool_call_id: "workflow-1",
                  tool_name: "google_ads_run_report",
                  args_sha256: "digest-only",
                  summary: "Run report",
                  status: "succeeded",
                  excerpt: '{"rows":3}',
                  presentation_result: {
                    results: [
                      {
                        connection_id: "connection-1",
                        data: {
                          currency_code: "GBP",
                          row_count: 1,
                          rows: [{ metrics: { clicks: "3" } }],
                          truncated: false,
                          truncation_note: null,
                        },
                        display_name: "Search account",
                        error_code: null,
                        error_message: null,
                        external_id: "1234567890",
                        status: "success",
                      },
                    ],
                  },
                },
                {
                  order: 2,
                  tool_call_id: "workflow-1:2",
                  parent_tool_call_id: "workflow-1",
                  tool_name: "read_file",
                  args_sha256: "digest-only",
                  summary: "Read file",
                  status: "failed",
                  excerpt: "File unavailable",
                },
              ],
            },
          },
        },
      ]),
    ])

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "workflow-1",
      name: "run_workflow",
      status: "completed",
      script: {
        code: "report = await google_ads_run_report(query='campaigns')\nreport",
        reason: "Find weak campaigns",
        status: "completed",
        children: [
          {
            id: "workflow-1:1",
            name: "google_ads_run_report",
            status: "completed",
            result: {
              results: [
                {
                  connection_id: "connection-1",
                  data: {
                    currency_code: "GBP",
                    row_count: 1,
                    rows: [{ metrics: { clicks: "3" } }],
                    truncated: false,
                    truncation_note: null,
                  },
                  display_name: "Search account",
                  error_code: null,
                  error_message: null,
                  external_id: "1234567890",
                  status: "success",
                },
              ],
            },
            resultExcerpt: '{"rows":3}',
          },
          {
            id: "workflow-1:2",
            name: "read_file",
            status: "failed",
            result: "File unavailable",
            resultExcerpt: "File unavailable",
          },
        ],
      },
    })
  })

  it("leaves legacy workflow messages without trace metadata as plain tool rows", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "workflow-1",
          tool_name: "run_workflow",
          args: { code: "'done'" },
        },
        {
          part_kind: "tool-return",
          tool_call_id: "workflow-1",
          tool_name: "run_workflow",
          outcome: "success",
          content: "done",
        },
      ]),
    ])

    expect(parsed[0]?.toolActivities[0]).not.toHaveProperty("script")
    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      name: "run_workflow",
      result: "done",
      status: "completed",
    })
  })

  it("renders a workflow call the run never answered as a stopped workflow card", () => {
    const dangling = [
      message(
        "message-1",
        "assistant",
        1,
        [
          {
            part_kind: "tool-call",
            tool_call_id: "workflow-1",
            tool_name: "run_workflow",
            args: { code: "r = await tool()", reason: "Adding keywords" },
          },
        ],
        { agent_run_id: "run-1" }
      ),
    ]

    for (const activeRun of [null, run("run-1", "failed")]) {
      const parsed = parseConversationMessages(dangling, activeRun)
      expect(parsed[0]?.toolActivities[0]).toMatchObject({
        name: "run_workflow",
        status: "failed",
        script: {
          children: [],
          code: "r = await tool()",
          reason: "Adding keywords",
          status: "failed",
        },
      })
    }
  })

  it("rebuilds a suspended workflow from the typed approval-state contract fixture", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "workflow-1",
              tool_name: "run_workflow",
              args: { code: "'stored separately'" },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "awaiting_approval"),
      [],
      undefined,
      {
        code: "report = await check_report(account='one')\nawait send_email(report=report)",
        nested_trace: [
          {
            position: 1,
            result_excerpt: '{"rows":3}',
            status: "succeeded",
            summary: "Check report",
            tool_call_id: "workflow-1:1",
            tool_name: "check_report",
          },
          {
            position: 2,
            result_excerpt: null,
            status: "pending",
            summary: "Send email",
            tool_call_id: "workflow-1:2",
            tool_name: "send_email",
          },
        ],
        outer_tool_call_id: "workflow-1",
        pending: {
          args: { subject: "Campaign update" },
          replay_args: { subject: "Campaign update" },
          derived_from_untrusted: true,
          taint_sources: [{ source_kind: "gmail_message", source_ref: "message-1" }],
          name: "send_email",
          parent_tool_call_id: "workflow-1",
          tool_call_id: "workflow-1:2",
        },
        reason: "Check the account and share an update",
        recovery: null,
        status: "suspended",
        trace_truncated: false,
      }
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "workflow-1",
      status: "awaiting_approval",
      script: {
        code: "report = await check_report(account='one')\nawait send_email(report=report)",
        reason: "Check the account and share an update",
        status: "awaiting_approval",
        children: [
          { id: "workflow-1:1", status: "completed" },
          {
            args: { subject: "Campaign update" },
            id: "workflow-1:2",
            name: "send_email",
            status: "awaiting_approval",
            derivedFromUntrusted: true,
            taintSources: [{ source_kind: "gmail_message", source_ref: "message-1" }],
          },
        ],
      },
    })
  })

  it.each([
    {
      name: "failed",
      outcome: "failed",
      traceStatus: "failed",
      expectedStatus: "failed",
    },
    {
      name: "resumed",
      outcome: "success",
      traceStatus: "succeeded",
      expectedStatus: "completed",
    },
  ])(
    "replays a $name workflow from its settled trace",
    ({ outcome, traceStatus, expectedStatus }) => {
      const parsed = parseConversationMessages([
        message("message-1", "assistant", 1, [
          {
            args: { code: "await check_report(account='one')" },
            part_kind: "tool-call",
            tool_call_id: "workflow-1",
            tool_name: "run_workflow",
          },
          {
            content: outcome === "failed" ? { error: "Stopped" } : "done",
            metadata: {
              code_mode_trace: {
                calls: [
                  {
                    excerpt: outcome === "failed" ? "Stopped" : '{"rows":3}',
                    status: traceStatus,
                    tool_call_id: "workflow-1:1",
                    tool_name: "check_report",
                  },
                ],
              },
            },
            outcome,
            part_kind: "tool-return",
            tool_call_id: "workflow-1",
            tool_name: "run_workflow",
          },
        ]),
      ])

      expect(parsed[0]?.toolActivities[0]).toMatchObject({
        status: expectedStatus,
        script: {
          status: expectedStatus,
          children: [{ status: expectedStatus }],
        },
      })
    }
  )

  it("keeps the partial workflow visible when a suspended run expires", () => {
    const pendingWorkflow = {
      code: "await send_email(subject='Update')",
      nested_trace: [],
      outer_tool_call_id: "workflow-1",
      pending: {
        args: { subject: "Update" },
        name: "send_email",
        parent_tool_call_id: "workflow-1",
        tool_call_id: "workflow-1:1",
      },
      reason: "Share the update",
      recovery: null,
      status: "suspended" as const,
      trace_truncated: false,
    }
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              args: { code: "await send_email(subject='Update')" },
              part_kind: "tool-call",
              tool_call_id: "workflow-1",
              tool_name: "run_workflow",
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "failed"),
      [],
      undefined,
      pendingWorkflow
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      status: "failed",
      script: {
        children: [{ id: "workflow-1:1", status: "awaiting_approval" }],
        reason: "Share the update",
      },
    })
  })

  it("advances an approved workflow child from live stream progress", () => {
    const pendingWorkflow = {
      code: "await send_email(subject='Update')",
      nested_trace: [],
      outer_tool_call_id: "workflow-1",
      pending: {
        args: { subject: "Update" },
        name: "send_email",
        parent_tool_call_id: "workflow-1",
        tool_call_id: "workflow-1:1",
      },
      reason: "Share the update",
      recovery: null,
      status: "suspended" as const,
      trace_truncated: false,
    }
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              args: { code: "await send_email(subject='Update')" },
              part_kind: "tool-call",
              tool_call_id: "workflow-1",
              tool_name: "run_workflow",
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "awaiting_approval"),
      [],
      new Map([
        [
          toolActivityIdentity("run-1", "workflow-1:1"),
          { result: { ok: true }, status: "completed" as const },
        ],
      ]),
      pendingWorkflow
    )

    const workflow = parsed[0]?.toolActivities[0]
    expect(workflow?.script?.children).toMatchObject([
      { id: "workflow-1:1", status: "completed", result: { ok: true } },
    ])
    expect(workflow?.script?.children.some((child) => child.status === "awaiting_approval")).toBe(
      false
    )
  })

  it("preserves capability-load metadata for skill activation rows", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "tool-call-1",
          tool_kind: "capability-load",
          tool_name: "load_capability",
          args: '{"id":"skill:skill-1"}',
        },
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_kind: "capability-load",
          tool_name: "load_capability",
          outcome: "success",
          content: { loaded: true },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities).toEqual([
      {
        id: "tool-call-1",
        agentRunId: null,
        kind: "call",
        status: "completed",
        name: "load_capability",
        args: { id: "skill:skill-1" },
        outcome: "success",
        result: { loaded: true },
        toolKind: "capability-load",
      },
    ])
  })

  it("uses explicit public tool-result metadata for persisted transcript display", () => {
    const parsed = parseConversationMessages([
      message("message-1", "tool", 1, [
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "google_ads_add_negative_keywords",
          outcome: "success",
          content: { counts: { added: 500 }, samples: { added: [] } },
          metadata: {
            public_result: {
              counts: { added: 500 },
              rows: Array.from({ length: 500 }, (_, index) => ({ id: index })),
            },
          },
        },
      ]),
    ])

    expect(parsed[0]?.toolActivities[0]?.result).toMatchObject({
      counts: { added: 500 },
    })
    expect((parsed[0]?.toolActivities[0]?.result as { rows: { id: number }[] }).rows).toHaveLength(
      500
    )
  })

  it.each([
    { name: "absent", metadata: {}, expected: { model_only: "must-not-leak" } },
    { name: "null", metadata: { public_result: null }, expected: null },
    { name: "false", metadata: { public_result: false }, expected: false },
    { name: "zero", metadata: { public_result: 0 }, expected: 0 },
    { name: "empty string", metadata: { public_result: "" }, expected: "" },
    { name: "object", metadata: { public_result: { rows: [] } }, expected: { rows: [] } },
    { name: "list", metadata: { public_result: [] }, expected: [] },
  ])("honors $name public-result presence in persisted messages", ({ metadata, expected }) => {
    const parsed = parseConversationMessages([
      message("message-1", "tool", 1, [
        {
          part_kind: "tool-return",
          tool_call_id: "tool-call-1",
          tool_name: "test_tool",
          outcome: "success",
          content: { model_only: "must-not-leak" },
          metadata,
        },
      ]),
    ])

    expect(parsed[0]?.toolActivities[0]?.result).toEqual(expected)
  })

  it("groups delegation call and return details under one activity", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        {
          part_kind: "tool-call",
          tool_call_id: "delegate-1",
          tool_name: "delegate_to_agent",
          args: {
            agent_id: "agent-2",
            task: "Research the launch plan",
          },
        },
      ]),
      message("message-2", "tool", 2, [
        {
          part_kind: "tool-return",
          tool_call_id: "delegate-1",
          tool_name: "delegate_to_agent",
          outcome: "success",
          content: {
            agent_id: "agent-2",
            agent_name: "Researcher",
            conversation_id: "conversation-2",
            output: "Research complete",
            pending_approvals: [],
            run_id: "run-2",
            status: "completed",
          },
        },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "delegate-1",
      kind: "call",
      status: "completed",
      name: "delegate_to_agent",
      delegate: {
        agentId: "agent-2",
        agentName: "Researcher",
        conversationId: "conversation-2",
        output: "Research complete",
        pendingApprovalCount: 0,
        runId: "run-2",
        status: "completed",
        taskPreview: "Research the launch plan",
        truncated: false,
      },
    })
  })

  it("merges pending delegated approvals into a running delegation call", () => {
    const delegations: PendingDelegatedApproval[] = [
      {
        parent_tool_call_id: "delegate-1",
        child_agent_id: "agent-2",
        child_agent_name: "Researcher",
        child_conversation_id: "conversation-2",
        child_run_id: "run-2",
        pending_approval_count: 2,
      },
    ]

    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "delegate-1",
              tool_name: "delegate_to_agent",
              args: { agent_id: "agent-2", task: "Check approvals" },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "awaiting_approval"),
      delegations
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      kind: "approval",
      status: "awaiting_approval",
      delegate: {
        agentId: "agent-2",
        agentName: "Researcher",
        conversationId: "conversation-2",
        pendingApprovalCount: 2,
        runId: "run-2",
        status: "awaiting_approval",
        taskPreview: "Check approvals",
      },
    })
  })

  it("only marks an unresolved call from the active run as awaiting approval", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-old",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "write_file",
              args: { name: "old.txt" },
            },
          ],
          { agent_run_id: "run-old" }
        ),
        message(
          "message-active",
          "assistant",
          2,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "write_file",
              args: { name: "active.txt" },
            },
          ],
          { agent_run_id: "run-active" }
        ),
      ],
      run("run-active", "awaiting_approval")
    )

    expect(parsed.map((item) => item.toolActivities[0])).toMatchObject([
      {
        agentRunId: "run-old",
        args: { name: "old.txt" },
        kind: "call",
        status: "unknown",
      },
      {
        agentRunId: "run-active",
        args: { name: "active.txt" },
        kind: "approval",
        status: "awaiting_approval",
      },
    ])
  })

  it("keeps unknown parts as unsupported renderable content", () => {
    const parsed = parseConversationMessages([
      message("message-1", "assistant", 1, [
        { part_kind: "strange-part", content: { value: "unhandled" } },
      ]),
    ])

    expect(parsed).toHaveLength(1)
    expect(parsed[0]?.text).toEqual([])
    expect(parsed[0]?.toolActivities).toEqual([])
    expect(parsed[0]?.unsupportedParts).toHaveLength(1)
    expect(parsed[0]?.unsupportedParts[0]).toMatchObject({
      id: "message-1:0",
      label: "Strange Part",
    })
    expect(parsed[0]?.unsupportedParts[0]?.preview).toContain("unhandled")
  })

  it("preserves input ordering and sequence values for identical timestamps", () => {
    const messages = [
      message("message-2", "assistant", 2, [{ part_kind: "text", content: "Second" }]),
      message("message-1", "assistant", 1, [{ part_kind: "text", content: "First" }]),
    ]

    const parsed = parseConversationMessages(messages, run("run-1", "completed"))

    expect(parsed.map((item) => item.id)).toEqual(["message-2", "message-1"])
    expect(parsed.map((item) => item.sequence)).toEqual([2, 1])
  })

  it("completes a persisted call from a live stream result before persistence catches up", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "tool-call-1",
              tool_name: "gmail_send_message",
              args: { to: ["a@example.com"] },
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "running"),
      [],
      new Map([
        [
          toolActivityIdentity("run-1", "tool-call-1"),
          { result: { results: [] }, status: "completed" as const },
        ],
      ])
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "tool-call-1",
      status: "completed",
      result: { results: [] },
    })
  })

  it("keeps a call running when no live result exists for it", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-1",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "tool-call-1",
              tool_name: "gmail_send_message",
              args: {},
            },
          ],
          { agent_run_id: "run-1" }
        ),
      ],
      run("run-1", "running"),
      [],
      new Map([
        [
          toolActivityIdentity("run-1", "other-call"),
          { result: "done", status: "completed" as const },
        ],
      ])
    )

    expect(parsed[0]?.toolActivities[0]).toMatchObject({
      id: "tool-call-1",
      status: "running",
    })
  })

  it("only merges a live result into the matching run when a call id is reused", () => {
    const parsed = parseConversationMessages(
      [
        message(
          "message-old",
          "assistant",
          1,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "web_search",
              args: { query: "old" },
            },
          ],
          { agent_run_id: "run-old" }
        ),
        message(
          "message-active",
          "assistant",
          2,
          [
            {
              part_kind: "tool-call",
              tool_call_id: "reused-call",
              tool_name: "web_search",
              args: { query: "active" },
            },
          ],
          { agent_run_id: "run-active" }
        ),
      ],
      run("run-active", "running"),
      [],
      new Map([
        [
          toolActivityIdentity("run-active", "reused-call"),
          { result: { answer: "active result" }, status: "completed" as const },
        ],
      ])
    )

    expect(parsed.map((item) => item.toolActivities[0])).toMatchObject([
      {
        agentRunId: "run-old",
        args: { query: "old" },
        status: "unknown",
      },
      {
        agentRunId: "run-active",
        args: { query: "active" },
        result: { answer: "active result" },
        status: "completed",
      },
    ])
  })
})
