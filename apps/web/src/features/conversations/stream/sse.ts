// apps/web/src/features/conversations/stream/sse.ts

import {
  isStreamEventName,
  type StreamEvent,
  type StreamEventName,
} from "@/features/conversations/stream/protocol"
import { isRecord } from "@/lib/guards"

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array> | null
): AsyncGenerator<StreamEvent> {
  if (stream === null) {
    throw new Error("Stream response did not include a readable body.")
  }

  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    for (;;) {
      const result = await reader.read()
      if (result.done) {
        break
      }

      buffer = normalizeLineEndings(`${buffer}${decoder.decode(result.value, { stream: true })}`)

      let frameEnd = buffer.indexOf("\n\n")
      while (frameEnd !== -1) {
        const frame = buffer.slice(0, frameEnd)
        buffer = buffer.slice(frameEnd + 2)

        const event = parseSseFrame(frame)
        if (event !== null) {
          yield event
        }

        frameEnd = buffer.indexOf("\n\n")
      }
    }

    buffer = normalizeLineEndings(`${buffer}${decoder.decode()}`)
    if (buffer.trim().length > 0) {
      const event = parseSseFrame(buffer)
      if (event !== null) {
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseSseFrame(frame: string): StreamEvent | null {
  let eventName: StreamEventName | null = null
  const dataLines: string[] = []
  let hasDataOrEventField = false

  for (const line of frame.split("\n")) {
    if (line.length === 0 || line.startsWith(":")) {
      continue
    }

    const separatorIndex = line.indexOf(":")
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex)
    const rawValue = separatorIndex === -1 ? "" : line.slice(separatorIndex + 1)
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue

    if (field === "event") {
      hasDataOrEventField = true
      if (!isStreamEventName(value)) {
        throw new Error(`Unsupported stream event "${value}".`)
      }
      eventName = value
      continue
    }

    if (field === "data") {
      hasDataOrEventField = true
      dataLines.push(value)
    }
  }

  if (!hasDataOrEventField) {
    return null
  }

  if (eventName === null) {
    throw new Error("SSE frame is missing an event name.")
  }

  if (dataLines.length === 0) {
    throw new Error(`SSE event "${eventName}" is missing JSON data.`)
  }

  const parsed = parseJsonData(eventName, dataLines.join("\n"))
  if (!isRecord(parsed)) {
    throw new Error(`SSE event "${eventName}" data must be a JSON object.`)
  }

  return { event: eventName, data: parsed } as StreamEvent
}

function parseJsonData(eventName: StreamEventName, value: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown JSON parse error"
    throw new Error(`Invalid JSON for SSE event "${eventName}": ${detail}`, {
      cause: error,
    })
  }
}

function normalizeLineEndings(value: string) {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}
