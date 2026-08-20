import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api/client", () => ({
  apiRequest: vi.fn(),
  setApiRequestHeadersProvider: vi.fn(),
}))

import { EntityFieldInput } from "@/components/tool-ui/entity-field-input"
import {
  entityReferenceHydrationQueryOptions,
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
  type EntityReferenceHydration,
} from "@/components/tool-ui/entity-reference-queries"
import type { EntityChoice } from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"
import { isRecord } from "@/lib/guards"

const field = {
  key: "file_id",
  label: "File",
  min_rows: 0,
  format: "entity" as const,
  editable: true,
  placeholder: "",
  options: [],
  secondary: false,
  entity_kind: "file",
}

function renderEntityInput(value: unknown, choices: EntityChoice[] = []): string {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const request: EntityReferenceHydration = {
    conversationId: "conversation-1",
    dependentArgs: { file_id: value },
    exactValues: isRecord(value) ? [value] : [],
    fieldKey: "file_id",
    toolName: "read_file",
  }
  if (choices.length > 0) {
    client.setQueryData(entityReferenceHydrationQueryOptions(request).queryKey, {
      entity_kind: "file",
      choices,
    })
  }
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(EntityFieldInput, {
        conversationId: request.conversationId,
        dependentArgs: request.dependentArgs,
        disabled: false,
        field,
        id: "file-picker",
        onChange: () => undefined,
        onValidityChange: () => undefined,
        toolName: request.toolName,
        value,
      })
    )
  )
}

describe("EntityFieldInput", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset()
  })

  it("blocks legacy raw identifiers with an explicit unavailable state", () => {
    const html = renderEntityInput("opaque-file-id")

    expect(html).toContain("Target unavailable")
    expect(html).not.toContain("opaque-file-id")
  })

  it("prompts for a selection instead of reporting an unavailable target when empty", () => {
    const html = renderEntityInput(null)

    expect(html).toContain("Choose a target to continue.")
    expect(html).not.toContain("Target unavailable")
  })

  it("hydrates and displays the canonical server label without exposing IDs", () => {
    const value = {
      version: 1,
      entity_kind: "file",
      entity_id: "opaque-file-id",
      label: "Untrusted label",
    }
    const html = renderEntityInput(value, [
      {
        identity: ["1", "file", "opaque-file-id"],
        value: { ...value, label: "Quarterly plan.pdf" },
        label: "Quarterly plan.pdf",
        description: "PDF · updated today",
        scope_label: "Operations",
      },
    ])

    expect(html).toContain('value="Quarterly plan.pdf"')
    expect(html).not.toContain("Untrusted label")
    expect(html).not.toContain("Target unavailable")
  })

  it("matches model-issued references that omit defaulted identity fields", () => {
    const value = { entity_id: "opaque-file-id", label: "Model label" }
    const html = renderEntityInput(value, [
      {
        identity: ["1", "file", "opaque-file-id"],
        value: {
          version: 1,
          entity_kind: "file",
          entity_id: "opaque-file-id",
          label: "Quarterly plan.pdf",
        },
        label: "Quarterly plan.pdf",
        description: "PDF · updated today",
        scope_label: "Operations",
      },
    ])

    expect(html).toContain('value="Quarterly plan.pdf"')
    expect(html).not.toContain("Target unavailable")
  })

  it("uses a canonical server-hydrated identity for a model-issued reference", () => {
    const value = {
      customer_id: "123",
      shared_set_id: "456",
      label: "Testing 2",
    }
    const html = renderEntityInput(value, [
      {
        identity: ["1", "google_ads_shared_set", "123", "456"],
        value: {
          version: 1,
          entity_kind: "google_ads_shared_set",
          customer_id: "123",
          shared_set_id: "456",
          label: "Testing 2",
        },
        label: "Testing 2",
        description: "0 negative keywords",
        scope_label: "Ads account",
      },
    ])

    expect(html).toContain('value="Testing 2"')
    expect(html).not.toContain("Target unavailable")
  })

  it("merges paged choices by identity", () => {
    const duplicate: EntityChoice = {
      identity: ["1", "file", "duplicate-id"],
      value: {
        version: 1,
        entity_kind: "file",
        entity_id: "duplicate-id",
        label: "Duplicate target",
      },
      label: "Duplicate target",
      description: null,
      scope_label: null,
    }
    const choices = mergeEntityChoices([], [{ choices: [duplicate] }, { choices: [duplicate] }])

    expect(choices).toEqual([duplicate])
  })

  it("isolates search generations and forwards TanStack Query cancellation", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      entity_kind: "file",
      choices: [],
      next_cursor: null,
    })
    const base = {
      conversationId: "conversation-1",
      dependentArgs: {},
      fieldKey: "file_id",
      toolName: "read_file",
    }
    const first = entityReferenceSearchQueryOptions({ ...base, search: "first" })
    const second = entityReferenceSearchQueryOptions({ ...base, search: "second" })
    const signal = new AbortController().signal
    if (typeof second.queryFn !== "function") {
      throw new Error("Expected an entity search query function")
    }

    await second.queryFn({
      client: new QueryClient(),
      direction: "forward",
      meta: undefined,
      pageParam: "cursor-2",
      queryKey: second.queryKey,
      signal,
    })

    expect(first.queryKey).not.toEqual(second.queryKey)
    const [path, options] = vi.mocked(apiRequest).mock.calls[0] ?? []
    expect(path).toBe("/tools/conversations/conversation-1/entity-references")
    expect(options?.signal).toBe(signal)
    expect(options?.body).toMatchObject({ search: "second", cursor: "cursor-2" })
  })
})
