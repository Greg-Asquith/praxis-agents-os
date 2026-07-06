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
})
