// apps/web/tests/integrations/meta-ads/targeting-sentence.test.ts

import { describe, expect, it } from "vitest"
import { targetingSentences } from "@/integrations/meta_ads/lib/targeting-sentence"

const draft = {
  locations: [{ kind: "country", key: "GB", name: "United Kingdom" }],
  age_min: 25,
  age_max: 54,
  detailed: [[{ kind: "interest", key: "6003", name: "Running" }]],
}

describe("Meta Ads targeting sentence", () => {
  it("warns that Advantage+ audience can reach outside the age range unless it is off", () => {
    expect(targetingSentences(draft).at(-1)).toMatch(/Advantage\+ audience is on/)
    expect(targetingSentences({ ...draft, advantage_audience: false })).toEqual([
      "People of all genders aged 25 to 54 in United Kingdom.",
      "Must match Running.",
    ])
  })

  it("states the special ad category limits", () => {
    const sentences = targetingSentences(
      { ...draft, advantage_audience: false },
      { specialCategory: true }
    )

    expect(sentences.at(-1)).toMatch(/Housing, employment, or financial ad/)
  })
})
