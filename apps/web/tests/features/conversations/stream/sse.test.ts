import { describe, expect, it } from "vitest"

import { parseSseStream } from "@/features/conversations/stream/sse"

function streamFromChunks(chunks: string[]) {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

async function collectEvents(chunks: string[]) {
  const events = []
  for await (const event of parseSseStream(streamFromChunks(chunks))) {
    events.push(event)
  }
  return events
}

function eventFrame(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

const envelope = {
  run_id: "run-1",
  conversation_id: "conversation-1",
  seq: 1,
}

const conversation = {
  id: "conversation-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  created_by: "user-1",
  title: null,
  description: "A conversation",
  status: "active",
  metadata: { source: "test" },
  unread: false,
  source: "direct",
  last_message_at: null,
  active_agent_id: "agent-1",
  agent_slug: null,
  agent_name: "Research agent",
  active_run_id: "run-1",
  active_run_status: "running",
  needs_approval: false,
  created_at: "2026-08-03T10:00:00Z",
  updated_at: "2026-08-03T10:00:01Z",
}

const validEventCases = [
  ["conversation.created", { ...envelope, conversation }],
  ["conversation.updated", { ...envelope, conversation }],
  ["run.status", { ...envelope, status: "running" }],
  [
    "message.start",
    { ...envelope, message_id: "message-1", role: "assistant", channel: "thinking" },
  ],
  ["message.delta", { ...envelope, message_id: "message-1", text: "Hello" }],
  ["message.end", { ...envelope, message_id: "message-1" }],
  [
    "tool.call",
    {
      ...envelope,
      tool_call_id: "tool-1",
      parent_tool_call_id: "workflow-1",
      name: "search",
      args: null,
    },
  ],
  [
    "tool.result",
    {
      ...envelope,
      tool_call_id: "tool-1",
      parent_tool_call_id: "workflow-1",
      name: null,
      result: ["result"],
    },
  ],
  [
    "tool.approval_required",
    {
      ...envelope,
      tool_call_id: "tool-1",
      parent_tool_call_id: "workflow-1",
      name: "send_email",
      args: { to: "operator@example.com" },
      replay_args: null,
      derived_from_untrusted: true,
      taint_sources: [{ source_kind: "gmail_message", source_ref: "message-1" }],
      delegation: {
        parent_tool_call_id: "parent-tool-1",
        child_agent_id: "agent-2",
        child_agent_name: "Email agent",
        child_conversation_id: "conversation-2",
        child_run_id: "run-2",
        pending_approval_count: 1,
      },
    },
  ],
  [
    "workflow.state",
    {
      ...envelope,
      tool_call_id: "workflow-1",
      state: "completed",
      output_excerpt: "two rows",
      error_excerpt: null,
    },
  ],
  ["error", { ...envelope, code: "provider_failure", message: "Provider failed." }],
  ["done", { ...envelope, status: "completed" }],
] as const

describe("parseSseStream", () => {
  it("parses a single complete event", async () => {
    await expect(
      collectEvents([
        'event: run.status\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":1,"status":"running"}\n\n',
      ])
    ).resolves.toEqual([
      {
        event: "run.status",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 1,
          status: "running",
        },
      },
    ])
  })

  it("parses one event split across multiple chunks", async () => {
    await expect(
      collectEvents([
        "event: message.delta\n",
        'data: {"run_id":"run-1","conversation_id":"conversation-1","seq":2,',
        '"message_id":"message-1","text":"Hello"}\n\n',
      ])
    ).resolves.toEqual([
      {
        event: "message.delta",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 2,
          message_id: "message-1",
          text: "Hello",
        },
      },
    ])
  })

  it("parses multiple events from one chunk", async () => {
    await expect(
      collectEvents([
        'event: message.start\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":3,"message_id":"message-1","role":"assistant"}\n\n' +
          'event: message.end\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":4,"message_id":"message-1"}\n\n',
      ])
    ).resolves.toEqual([
      {
        event: "message.start",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 3,
          message_id: "message-1",
          role: "assistant",
        },
      },
      {
        event: "message.end",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 4,
          message_id: "message-1",
        },
      },
    ])
  })

  it("accepts a live workflow sequence with parented nested calls", async () => {
    const events = [
      ["workflow.state", { ...envelope, seq: 1, tool_call_id: "workflow-1", state: "started" }],
      [
        "tool.call",
        {
          ...envelope,
          seq: 2,
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "search",
          args: { query: "status" },
        },
      ],
      [
        "tool.result",
        {
          ...envelope,
          seq: 3,
          tool_call_id: "workflow-1:1",
          parent_tool_call_id: "workflow-1",
          name: "search",
          result: { count: 1 },
        },
      ],
      ["workflow.state", { ...envelope, seq: 4, tool_call_id: "workflow-1", state: "completed" }],
    ] as const

    await expect(
      collectEvents(events.map(([event, data]) => eventFrame(event, data)))
    ).resolves.toEqual(events.map(([event, data]) => ({ event, data })))
  })

  it("handles CRLF separators", async () => {
    await expect(
      collectEvents([
        'event: done\r\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":5,"status":"completed"}\r\n\r\n',
      ])
    ).resolves.toEqual([
      {
        event: "done",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 5,
          status: "completed",
        },
      },
    ])
  })

  it("ignores keepalive comment frames", async () => {
    await expect(
      collectEvents([
        ": keepalive\n\n" +
          'event: run.status\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":6,"status":"pending"}\n\n',
      ])
    ).resolves.toEqual([
      {
        event: "run.status",
        data: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          seq: 6,
          status: "pending",
        },
      },
    ])
  })

  it("throws for unknown event names", async () => {
    await expect(
      collectEvents([
        'event: agent.surprise\ndata: {"run_id":"run-1","conversation_id":"conversation-1","seq":7}\n\n',
      ])
    ).rejects.toThrow('Unsupported stream event "agent.surprise".')
  })

  it.each(validEventCases)("validates the %s payload", async (event, data) => {
    await expect(collectEvents([eventFrame(event, data)])).resolves.toEqual([{ event, data }])
  })

  it("accepts omitted and null optional fields", async () => {
    const events = [
      ["message.start", { ...envelope, message_id: "message-1", role: "assistant" }],
      ["tool.result", { ...envelope, tool_call_id: "tool-1", result: null }],
      ["workflow.state", { ...envelope, tool_call_id: "workflow-1", state: "started" }],
      [
        "tool.approval_required",
        {
          ...envelope,
          tool_call_id: "tool-1",
          name: "send_email",
          args: {},
          delegation: null,
        },
      ],
    ] as const

    await expect(
      collectEvents(events.map(([event, data]) => eventFrame(event, data)))
    ).resolves.toEqual(events.map(([event, data]) => ({ event, data })))
  })

  it.each([
    ["missing run id", { conversation_id: "conversation-1", seq: 1, status: "running" }, "run_id"],
    [
      "empty conversation id",
      { ...envelope, conversation_id: "", status: "running" },
      "conversation_id",
    ],
    [
      "missing sequence",
      { run_id: "run-1", conversation_id: "conversation-1", status: "running" },
      "seq",
    ],
    ["non-numeric sequence", { ...envelope, seq: "1", status: "running" }, "seq"],
    ["non-positive sequence", { ...envelope, seq: 0, status: "running" }, "seq"],
  ])("rejects a %s", async (_name, data, field) => {
    await expect(collectEvents([eventFrame("run.status", data)])).rejects.toThrow(
      `Invalid SSE event "run.status": field "data.${field}"`
    )
  })

  it.each([
    ["conversation.created", { ...envelope }, "data.conversation"],
    [
      "conversation.updated",
      { ...envelope, conversation: { ...conversation, needs_approval: "false" } },
      "data.conversation.needs_approval",
    ],
    ["run.status", { ...envelope, status: "surprising" }, "data.status"],
    ["message.start", { ...envelope, message_id: "message-1", role: "user" }, "data.role"],
    ["message.delta", { ...envelope, message_id: "message-1", text: 42 }, "data.text"],
    ["message.end", { ...envelope, message_id: null }, "data.message_id"],
    ["tool.call", { ...envelope, tool_call_id: "tool-1", name: "search" }, "data.args"],
    ["tool.result", { ...envelope, tool_call_id: "tool-1" }, "data.result"],
    ["workflow.state", { ...envelope, tool_call_id: "workflow-1" }, "data.state"],
    [
      "tool.approval_required",
      {
        ...envelope,
        tool_call_id: "tool-1",
        name: "send_email",
        args: {},
        delegation: { pending_approval_count: "1" },
      },
      "data.delegation.parent_tool_call_id",
    ],
    ["error", { ...envelope, code: 500, message: "Failed" }, "data.code"],
    ["done", { ...envelope, status: null }, "data.status"],
  ])("rejects a malformed %s payload", async (event, data, field) => {
    await expect(collectEvents([eventFrame(event, data)])).rejects.toThrow(
      `Invalid SSE event "${event}": field "${field}"`
    )
  })

  it.each([
    [
      "message.start",
      { ...envelope, message_id: "message-1", role: "assistant", channel: null },
      "data.channel",
    ],
    ["tool.result", { ...envelope, tool_call_id: "tool-1", name: 10, result: null }, "data.name"],
    [
      "tool.call",
      {
        ...envelope,
        tool_call_id: "tool-1",
        parent_tool_call_id: "",
        name: "search",
        args: {},
      },
      "data.parent_tool_call_id",
    ],
    ["workflow.state", { ...envelope, tool_call_id: "workflow-1", state: "paused" }, "data.state"],
    [
      "tool.approval_required",
      {
        ...envelope,
        tool_call_id: "tool-1",
        parent_tool_call_id: "",
        name: "send_email",
        args: {},
      },
      "data.parent_tool_call_id",
    ],
    [
      "tool.approval_required",
      {
        ...envelope,
        tool_call_id: "tool-1",
        name: "send_email",
        args: {},
        delegation: [],
      },
      "data.delegation",
    ],
  ])("rejects an invalid optional field on %s", async (event, data, field) => {
    await expect(collectEvents([eventFrame(event, data)])).rejects.toThrow(
      `Invalid SSE event "${event}": field "${field}"`
    )
  })
})
