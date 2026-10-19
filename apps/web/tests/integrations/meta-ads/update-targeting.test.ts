// apps/web/tests/integrations/meta-ads/update-targeting.test.ts

import { describe, expect, it } from "vitest"

import {
  currentProblems,
  listState,
  parseTargetingEditArgs,
  targetingAfter,
  targetingEditRows,
  withItem,
  withoutItem,
  type TargetingEditArgs,
} from "@/integrations/meta_ads/lib/targeting-edits"
import { metaAdsUpdateTargetingPresenter } from "@/integrations/meta_ads/presenters/update-targeting"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

const adSet = {
  version: 1,
  entity_kind: "meta_ads_ad_set",
  label: "UK Prospecting",
  account_id: "111",
  campaign_id: "9",
  adset_id: "8",
}
const ireland = { kind: "country", key: "IE", name: "Ireland" }
const wales = {
  version: 1,
  account_id: "111",
  kind: "region",
  key: "4079",
  name: "Wales",
  label: "Wales",
}
const buyers = { label: "Purchasers", account_id: "111", audience_id: "301" }
const entry = { add_locations: [ireland], remove_audiences: [buyers] }
const before = {
  locations: [{ kind: "country", key: "GB", name: null }],
  location_types: "home_or_recent",
  age_min: 18,
  age_max: null,
  genders: "all",
  audiences: [{ ...buyers, entity_kind: "meta_ads_audience" }],
  excluded_audiences: [],
  detailed: [],
  advantage_audience: true,
}

function args(change: Record<string, unknown>, problems: string[] = []) {
  return {
    changes: [{ ad_set: adSet, ...change }],
    _checks: {
      "8": { unavailable: false, before, requested: entry, problems, warnings: [], notes: [] },
    },
  }
}

function parse(change: Record<string, unknown>) {
  const parsed = parseTargetingEditArgs(args(change, ["Too narrow."]))
  if (!parsed) throw new Error("expected targeting edit args")
  return parsed
}

function first(parsed: TargetingEditArgs) {
  const [edit] = parsed.edits
  if (!edit) throw new Error("expected one ad set")
  return edit
}

describe("Meta Ads targeting edits", () => {
  it("applies additions and removals to the targeting the ad set has now", () => {
    const after = targetingAfter(before, entry)

    expect(after["locations"]).toEqual([...before.locations, ireland])
    expect(after["audiences"]).toEqual([])
  })

  it("lets the operator remove and add places, and undoing returns to Meta's checks", () => {
    const proposed = parse(entry)
    const [row] = targetingEditRows(proposed, proposed)
    if (!row) throw new Error("expected one ad set")
    const [uk] = listState(row, "locations").items
    if (!uk) throw new Error("expected the current place")

    const edited = withItem(withoutItem(row.edit.raw, "locations", uk), "locations", wales)
    expect(edited["remove_locations"]).toEqual([
      { kind: "country", key: "GB", name: "United Kingdom" },
    ])
    expect(edited["add_locations"]).toEqual([
      ireland,
      { kind: "region", key: "4079", name: "Wales" },
    ])
    expect(currentProblems(first(parse(edited)))).toEqual([])

    const [undone] = targetingEditRows(proposed, parse(edited))
    if (!undone) throw new Error("expected one ad set")
    const [ukAgain] = listState(undone, "locations").removing
    const added = listState(undone, "locations").items.find((item) => item.label === "Wales")
    if (!ukAgain || !added) throw new Error("expected the removal and the addition")
    const restored = withoutItem(withItem(edited, "locations", ukAgain.item), "locations", added)
    expect(currentProblems(first(parse(restored)))).toEqual(["Too narrow."])
  })
})

describe("Meta Ads update targeting presenter", () => {
  it("shows each ad set's changes, and blocks what Meta won't accept", () => {
    const html = render(approval(args(entry)))
    expect(html).toContain("+Ireland")
    expect(html).not.toMatch(APPROVE_DISABLED)

    expect(render(approval(args(entry, ["Housing ads can't exclude locations."])))).toMatch(
      APPROVE_DISABLED
    )
  })
})

function approval(value: Record<string, unknown>) {
  return metaAdsUpdateTargetingPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_update_targeting",
        status: "awaiting_approval",
        args: value,
      },
      true
    )
  )
}
