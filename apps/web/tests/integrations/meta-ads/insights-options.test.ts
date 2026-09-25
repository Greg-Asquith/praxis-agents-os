import { describe, expect, it } from "vitest"

import { parseInsightsOptions } from "@/integrations/meta_ads/lib/insights-options"

import formSchema from "./insights-form-schema.json"

describe("Insights option validation", () => {
  it.each([
    { level: { $ref: "https://example.com/schema" } },
    { level: { $ref: "#/$defs/missing" } },
    { level: { enum: [], default: "account" } },
    { level: { enum: ["account", 1], default: "account" } },
    { limit: { minimum: "1", maximum: 100, default: 10 } },
    { limit: { minimum: 1, maximum: -1, default: 10 } },
    { limit: { minimum: 1, maximum: 100, default: 1.5 } },
    { fields: { type: "array", items: { examples: [] }, maxItems: 30 } },
    { filters: { anyOf: [{ type: "null" }] } },
    { time_increment: { anyOf: [{ enum: [] }], default: "all_days" } },
    { time_increment: { anyOf: [{ minimum: 2, maximum: 1 }], default: 1 } },
    { time_increment: { anyOf: [{ minimum: 0, maximum: 1001 }], default: 1 } },
    { sort: { "x-directions": ["ascending", false] } },
  ])("rejects malformed schema properties: %j", (properties) => {
    expect(
      parseInsightsOptions({
        ...formSchema,
        properties: { ...formSchema.properties, ...properties },
      })
    ).toBeNull()
  })
})
