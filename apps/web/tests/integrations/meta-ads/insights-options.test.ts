import { describe, expect, it } from "vitest"

import { parseInsightsOptions } from "@/integrations/meta_ads/lib/insights-options"

import formSchema from "./insights-form-schema.json"

describe("Insights option validation", () => {
  it.each([
    { level: { $ref: "https://example.com/schema" } },
    { limit: { minimum: 1, maximum: -1, default: 10 } },
    { time_increment: { anyOf: [{ minimum: 2, maximum: 1 }], default: 1 } },
  ])("rejects malformed schema properties: %j", (properties) => {
    expect(
      parseInsightsOptions({
        ...formSchema,
        properties: { ...formSchema.properties, ...properties },
      })
    ).toBeNull()
  })
})
