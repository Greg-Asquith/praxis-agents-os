import { describe, expect, it } from "vitest"

import {
  STREAM_EVENT_NAMES,
  STREAM_PROTOCOL_VERSION,
  STREAM_VERSION_HEADER,
  isStreamEventName,
} from "@/features/conversations/stream/protocol"
import protocolSamples from "./fixtures/protocol.samples.json"
import protocolSchema from "./fixtures/protocol.schema.json"
import {
  AGENT_RUN_STATUSES,
  CONVERSATION_SOURCES,
  MESSAGE_CHANNELS,
  STREAM_RUN_STATUSES,
  WORKFLOW_STATES,
  parseStreamEvent,
} from "@/features/conversations/stream/validation"
import { isRecord } from "@/lib/guards"

type Mutation = {
  path: string
  data: Record<string, unknown>
}

describe("agent stream protocol contract", () => {
  it("matches the backend version, event names, and enums", () => {
    expect(STREAM_PROTOCOL_VERSION).toBe(protocolSchema.version)
    expect(STREAM_VERSION_HEADER).toBe(protocolSchema.header)
    expect(STREAM_EVENT_NAMES).toEqual(protocolSchema.event_names)
    expect([...AGENT_RUN_STATUSES]).toEqual(protocolSchema.enums.agent_run_statuses)
    expect([...STREAM_RUN_STATUSES]).toEqual(protocolSchema.enums.stream_run_statuses)
    expect([...CONVERSATION_SOURCES]).toEqual(protocolSchema.enums.conversation_sources)
    expect([...MESSAGE_CHANNELS]).toEqual(protocolSchema.enums.message_channels)
    expect([...WORKFLOW_STATES]).toEqual(protocolSchema.enums.workflow_states)
  })

  it("accepts every backend sample and its schema-valid optional forms", () => {
    for (const [eventName, eventSchema] of Object.entries(protocolSchema.events)) {
      if (!isStreamEventName(eventName)) {
        throw new Error(`Schema contains unknown stream event ${eventName}.`)
      }
      const sample = protocolSamples.find((candidate) => candidate.event === eventName)
      if (sample === undefined) {
        throw new Error(`Schema event ${eventName} has no sample.`)
      }

      expect(parseStreamEvent(eventName, sample.data)).toBeDefined()

      const minimalData = removeOptionalFields(eventSchema, eventSchema, sample.data)
      if (!isRecord(minimalData)) {
        throw new Error(`Schema event ${eventName} did not produce an object payload.`)
      }
      expect(parseStreamEvent(eventName, minimalData)).toBeDefined()

      for (const mutation of nullableMutations(eventSchema, eventSchema, sample.data)) {
        expect(() => parseStreamEvent(eventName, mutation.data), mutation.path).not.toThrow()
      }
    }
  })

  it("rejects every missing required field, including nested fields", () => {
    for (const [eventName, eventSchema] of Object.entries(protocolSchema.events)) {
      if (!isStreamEventName(eventName)) {
        throw new Error(`Schema contains unknown stream event ${eventName}.`)
      }
      const sample = protocolSamples.find((candidate) => candidate.event === eventName)
      if (sample === undefined) {
        throw new Error(`Schema event ${eventName} has no sample.`)
      }

      for (const mutation of requiredFieldDeletions(eventSchema, eventSchema, sample.data)) {
        expect(() => parseStreamEvent(eventName, mutation.data), mutation.path).toThrow()
      }
    }
  })
})

function resolveSchema(
  rootSchema: Record<string, unknown>,
  schemaValue: unknown
): Record<string, unknown> {
  if (!isRecord(schemaValue)) {
    return {}
  }
  const reference = schemaValue["$ref"]
  if (typeof reference !== "string") {
    return schemaValue
  }
  const name = reference.split("/").at(-1)
  const definitions = rootSchema["$defs"]
  if (name === undefined || !isRecord(definitions)) {
    throw new Error(`Unresolvable stream schema reference ${reference}.`)
  }
  return resolveSchema(rootSchema, definitions[name])
}

function schemaAlternatives(schema: Record<string, unknown>): unknown[] {
  return Array.isArray(schema["anyOf"]) ? schema["anyOf"] : []
}

function removeOptionalFields(
  rootSchema: Record<string, unknown>,
  schemaValue: unknown,
  value: unknown
): unknown {
  const schema = resolveSchema(rootSchema, schemaValue)
  for (const alternative of schemaAlternatives(schema)) {
    const reduced = removeOptionalFields(rootSchema, alternative, value)
    if (reduced !== value || matchesSchemaType(alternative, value)) {
      return reduced
    }
  }
  if (schema["type"] === "object" && isRecord(value)) {
    const properties = isRecord(schema["properties"]) ? schema["properties"] : {}
    const required = new Set(
      Array.isArray(schema["required"])
        ? schema["required"].filter((key): key is string => typeof key === "string")
        : []
    )
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => required.has(key))
        .map(([key, child]) => [key, removeOptionalFields(rootSchema, properties[key], child)])
    )
  }
  if (schema["type"] === "array" && Array.isArray(value)) {
    return value.map((child) => removeOptionalFields(rootSchema, schema["items"], child))
  }
  return value
}

function requiredFieldDeletions(
  rootSchema: Record<string, unknown>,
  schemaValue: unknown,
  data: Record<string, unknown>
): Mutation[] {
  const mutations: Mutation[] = []
  visitSchema(rootSchema, schemaValue, data, [], (schema, value, path) => {
    if (schema["type"] !== "object" || !isRecord(value)) {
      return
    }
    const required = Array.isArray(schema["required"]) ? schema["required"] : []
    for (const key of required) {
      if (typeof key !== "string" || !Object.hasOwn(value, key)) {
        continue
      }
      const fieldPath = [...path, key]
      const mutated = withoutPath(data, fieldPath)
      if (!isRecord(mutated)) {
        throw new Error(`Deleting ${fieldPath.join(".")} removed the event payload.`)
      }
      mutations.push({ path: fieldPath.join("."), data: mutated })
    }
  })
  return mutations
}

function nullableMutations(
  rootSchema: Record<string, unknown>,
  schemaValue: unknown,
  data: Record<string, unknown>
): Mutation[] {
  const mutations: Mutation[] = []
  visitSchema(rootSchema, schemaValue, data, [], (schema, value, path) => {
    if (
      path.length === 0 ||
      value === null ||
      !schemaAlternatives(schema).some((candidate) =>
        isRecord(candidate) ? candidate["type"] === "null" : false
      )
    ) {
      return
    }
    const mutated = structuredClone(data)
    setAtPath(mutated, path, null)
    mutations.push({ path: path.join("."), data: mutated })
  })
  return mutations
}

function visitSchema(
  rootSchema: Record<string, unknown>,
  schemaValue: unknown,
  value: unknown,
  path: string[],
  visit: (schema: Record<string, unknown>, value: unknown, path: string[]) => void
): void {
  const schema = resolveSchema(rootSchema, schemaValue)
  visit(schema, value, path)
  for (const alternative of schemaAlternatives(schema)) {
    if (matchesSchemaType(alternative, value)) {
      visitSchema(rootSchema, alternative, value, path, visit)
    }
  }
  if (schema["type"] === "object" && isRecord(value)) {
    const properties = isRecord(schema["properties"]) ? schema["properties"] : {}
    for (const [key, child] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) {
        visitSchema(rootSchema, properties[key], child, [...path, key], visit)
      }
    }
  }
  if (schema["type"] === "array" && Array.isArray(value)) {
    value.forEach((child, index) => {
      visitSchema(rootSchema, schema["items"], child, [...path, String(index)], visit)
    })
  }
}

function matchesSchemaType(schemaValue: unknown, value: unknown): boolean {
  if (!isRecord(schemaValue)) {
    return false
  }
  switch (schemaValue["type"]) {
    case "null":
      return value === null
    case "object":
      return isRecord(value)
    case "array":
      return Array.isArray(value)
    case "string":
      return typeof value === "string"
    case "integer":
      return Number.isInteger(value)
    case "boolean":
      return typeof value === "boolean"
    default:
      return false
  }
}

function setAtPath(data: Record<string, unknown>, path: string[], value: unknown): void {
  const parent = valueAtPath(data, path.slice(0, -1))
  const key = path.at(-1)
  if (key === undefined) {
    return
  }
  if (Array.isArray(parent)) {
    parent[Number(key)] = value
  } else if (isRecord(parent)) {
    parent[key] = value
  }
}

function withoutPath(value: unknown, path: string[]): unknown {
  const [key, ...remaining] = path
  if (key === undefined) {
    return value
  }
  if (Array.isArray(value)) {
    return value.map<unknown>((child: unknown, index) =>
      index === Number(key) ? withoutPath(child, remaining) : child
    )
  }
  if (!isRecord(value)) {
    return value
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([candidate]) => remaining.length > 0 || candidate !== key)
      .map(([candidate, child]) => [
        candidate,
        candidate === key ? withoutPath(child, remaining) : child,
      ])
  )
}

function valueAtPath(value: unknown, path: string[]): unknown {
  return path.reduce<unknown>((current, key) => {
    if (Array.isArray(current)) {
      return current[Number(key)]
    }
    return isRecord(current) ? current[key] : undefined
  }, value)
}
