import { describe, expect, it } from "vitest"

import {
  auditProviderFilterOptions,
  auditToolFilterOptions,
} from "@/features/audit/audit-filter-options"
import type { ToolCatalogEntry } from "@/features/tools/types"

describe("audit filter options", () => {
  it("derives exact, deduplicated, label-sorted tool options", () => {
    const tools = [
      tool({ label: "Search messages", name: "gmail_search_messages", provider: "gmail" }),
      tool({ label: "Create record", name: "airtable_create_record", provider: "airtable" }),
      tool({ label: "Duplicate ignored", name: "gmail_search_messages", provider: "gmail" }),
    ]

    expect(auditToolFilterOptions(tools)).toEqual([
      { label: "Create record", value: "airtable_create_record" },
      { label: "Search messages", value: "gmail_search_messages" },
    ])
  })

  it("derives unique provider options with operator labels and stable ordering", () => {
    const tools = [
      tool({ name: "z", provider: "google_ads" }),
      tool({ name: "a", provider: "airtable" }),
      tool({ name: "b", provider: "google_ads" }),
      tool({ name: "c", provider: "bigquery" }),
    ]

    expect(auditProviderFilterOptions(tools)).toEqual([
      { label: "Airtable", value: "airtable" },
      { label: "Bigquery", value: "bigquery" },
      { label: "Google Ads", value: "google_ads" },
    ])
  })

  it("returns empty option lists for an empty catalog", () => {
    expect(auditToolFilterOptions([])).toEqual([])
    expect(auditProviderFilterOptions([])).toEqual([])
  })
})

function tool({
  label = "Tool label",
  name,
  provider,
}: {
  label?: string
  name: string
  provider: string
}): ToolCatalogEntry {
  return {
    name,
    provider,
    label,
    description: "Description",
    kind: "function",
    effect: "read",
    effect_scope: "external",
    egress: "provider_query",
    default_policy: "auto",
    supported_policies: ["auto"],
    defer_loading: false,
  }
}
