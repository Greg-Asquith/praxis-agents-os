// apps/web/tests/integrations/google-ads/update-targeting.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  keptRows,
  parseTime,
  rowWindows,
  scheduleProblems,
  scheduleRows,
  scheduleText,
  scheduleValid,
  type ScheduleWindow,
} from "@/integrations/google_ads/lib/ad-schedule"
import {
  addTarget,
  acceptsLanguageAdds,
  campaignRows,
  campaignsByDifference,
  clearedChange,
  editInScope,
  itemCount,
  needsCheck,
  parseBidAdjustment,
  parseUpdateTargetingArgs,
  pasteBatches,
  removeTarget,
  serializeChanges,
  EXCLUDED,
  setDevice,
  setSchedule,
  targetingApproveLabel,
  targetingBlock,
  targetingPrompt,
  unchangedPlaces,
  type Target,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"
import {
  addAudience,
  cancelAudience,
  demographicLines,
  setAudienceMode,
  setDemographic,
} from "@/integrations/google_ads/lib/targeting-audiences"
import { googleAdsSearchTargetingPresenter } from "@/integrations/google_ads/presenters/search-targeting"
import { googleAdsUpdateTargetingPresenter } from "@/integrations/google_ads/presenters/update-targeting"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/campaigns/${id}`

function campaign(id: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label: `Campaign ${id}` }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    name: "Trail",
    channel: "DISPLAY",
    problem: null,
    location_setting: "PRESENCE_OR_INTEREST",
    locations: [{ key: "2826", name: "United Kingdom", excluded: false, bid_adjustment: 0 }],
    location_total: 1,
    radius: [],
    languages: [{ key: "1000", name: "English" }],
    item_problems: [],
    already_set: [],
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [
      {
        campaign: campaign("10"),
        add_locations: [{ key: "1006", name: "Manchester", bid_adjustment: 15 }],
        exclude_locations: [],
        remove_locations: [],
        add_languages: [],
        remove_languages: [],
      },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      entries: { [key("10")]: check() },
      names: { locations: { "1006": "Manchester" }, languages: {} },
    },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateTargetingArgs {
  const args = parseUpdateTargetingArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

const LEEDS: Target = { bidAdjustment: null, key: "1007", name: "Leeds", targetType: "City" }

describe("targeting edits", () => {
  it("moves a location between lists instead of listing it twice", () => {
    const value = raw()
    const args = parsed(value)
    const excluded = addTarget(args.changes, "exclude_locations", {
      ...LEEDS,
      key: "1006",
      name: "Manchester",
    })

    expect(excluded[0]?.targets.add_locations).toEqual([])
    expect(excluded[0]?.targets.exclude_locations.map((item) => item.key)).toEqual(["1006"])
    // An excluded location can't carry a bid, and the server's model forbids the field.
    expect(serializeChanges(excluded)[0]?.["exclude_locations"]).toEqual([
      { key: "1006", name: "Manchester", target_type: "City" },
    ])
  })

  it("adds a language only to campaigns that can take one", () => {
    const value = raw({
      changes: [
        { campaign: campaign("10"), add_locations: [{ key: "1006" }] },
        { campaign: campaign("11"), add_locations: [{ key: "1006" }] },
      ],
      _checks: {
        entries: { [key("10")]: check({ channel: "SEARCH" }), [key("11")]: check() },
        names: {},
      },
    })
    const args = parsed(value)

    const next = addTarget(args.changes, "add_languages", { ...LEEDS, key: "1000" }, (change) =>
      acceptsLanguageAdds(args, change)
    )

    expect(next.map((change) => change.targets.add_languages.length)).toEqual([0, 1])
  })

  it("edits only the clicked campaign and keeps the others in their place", () => {
    const value = raw({
      changes: ["10", "11", "12"].map((id) => ({
        campaign: campaign(id),
        add_locations: [{ key: "1006" }],
      })),
    })
    const args = parsed(value)

    const added = editInScope(args.changes, key("11"), (changes) =>
      addTarget(changes, "add_locations", LEEDS)
    )
    expect(added.map((change) => change.targets.add_locations.length)).toEqual([1, 2, 1])

    // Emptying the clicked campaign takes only it out of the request.
    const removed = editInScope(args.changes, key("11"), (changes) =>
      removeTarget(changes, "add_locations", "1006")
    )
    expect(removed.map((change) => change.key)).toEqual([key("10"), key("12")])
  })

  it("takes a campaign out of the request when its last change is cancelled", () => {
    const args = parsed()

    expect(removeTarget(args.changes, "add_locations", "1006")).toEqual([])
  })
})

describe("approval", () => {
  it("blocks on a problem until the campaign is edited, then waits for a new check", () => {
    const value = raw({
      _checks: {
        entries: { [key("10")]: check({ problem: "This would leave no location." }) },
        names: {},
      },
    })
    const checked = parsed(value)

    expect(campaignRows(checked, checked)[0]?.problems).toEqual(["This would leave no location."])
    expect(targetingBlock(checked, checked)).toContain("Fix or cancel")

    const edited = parsed({
      ...value,
      changes: serializeChanges(addTarget(checked.changes, "add_locations", LEEDS)),
    })

    expect(campaignRows(edited, checked)[0]?.problems).toEqual([])
    expect(needsCheck(edited, checked)).toBe(true)
    expect(targetingBlock(edited, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("blocks and asks for a new check when Google couldn't be reached", () => {
    const args = parsed(raw({ _checks: { entries: { [key("10")]: { unavailable: true } } } }))

    expect(needsCheck(args, args)).toBe(true)
    expect(targetingBlock(args, args)).not.toBeNull()
  })

  it("doesn't count a campaign already at every setting", () => {
    const args = parsed(
      raw({
        _checks: {
          entries: {
            [key("10")]: check({ already_set: [{ field: "add_locations", key: "1006" }] }),
          },
          names: {},
        },
      })
    )

    expect(targetingApproveLabel(args)).toBe("Apply Changes")
    expect(targetingBlock(args, args)).toBe("These campaigns already have these settings.")
  })

  it("names the rejected item, and an edited draft with nothing changed needs no check", () => {
    const args = parsed(
      raw({
        _checks: {
          entries: {
            [key("10")]: check({
              item_problems: [
                { field: "add_locations", key: "1006", message: "Google says: Not allowed." },
              ],
            }),
          },
          names: {},
        },
      })
    )

    expect(campaignRows(args, args)[0]?.problems).toEqual(["Manchester: Google says: Not allowed."])
    expect(needsCheck(args, args)).toBe(false)
  })
})

describe("wording", () => {
  it("names one location on the button, and counts otherwise", () => {
    expect(targetingApproveLabel(parsed())).toBe("Add Manchester")
    expect(targetingPrompt(parsed())).toBe("Add Manchester to Trail in Northwind.")

    const two = parsed(
      raw({
        changes: [
          {
            campaign: campaign("10"),
            add_locations: [{ key: "1006" }, { key: "1007", name: "Leeds" }],
          },
        ],
      })
    )
    expect(targetingApproveLabel(two)).toBe("Add 2 Locations")

    const campaigns = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), add_locations: [{ key: "1006" }] },
          { campaign: campaign("11"), add_locations: [{ key: "1006" }] },
        ],
        _checks: {
          entries: {
            [key("10")]: check(),
            // A blocked campaign doesn't count towards what applies.
            [key("11")]: check({ problem: "Would leave no location." }),
          },
          names: {},
        },
      })
    )
    expect(targetingApproveLabel(campaigns)).toBe("Apply to 1 Campaign")
  })
})

describe("what the card lists", () => {
  it("counts live places per campaign and leaves out what the request touches", () => {
    const args = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), exclude_locations: [{ key: "2000" }] },
          { campaign: campaign("11"), add_locations: [{ key: "1006" }] },
        ],
        _checks: {
          entries: {
            [key("10")]: check({
              locations: [
                { key: "2826", name: "United Kingdom", excluded: false, bid_adjustment: 0 },
                { key: "2000", name: "Wales", excluded: false, bid_adjustment: 0 },
              ],
            }),
            [key("11")]: check(),
          },
          names: {},
        },
      })
    )

    expect(unchangedPlaces(args).map((place) => [place.name, place.count])).toEqual([
      ["United Kingdom", 2],
    ])
  })

  it("puts blocked campaigns first, then the ones least like the rest", () => {
    const same = { add_locations: [{ key: "1006" }] }
    const args = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), ...same },
          { campaign: campaign("11"), ...same },
          { campaign: campaign("12"), exclude_locations: [{ key: "1007" }] },
          { campaign: campaign("13"), ...same },
        ],
        _checks: {
          entries: {
            [key("10")]: check(),
            [key("11")]: check(),
            [key("12")]: check(),
            [key("13")]: check({ problem: "Would leave no location." }),
          },
          names: {},
        },
      })
    )

    const order = campaignsByDifference(campaignRows(args, args)).map((row) => row.key)
    expect(order.slice(0, 2)).toEqual([key("13"), key("12")])
  })

  it("starts a cancelled campaign again from nothing", () => {
    const [change] = parsed().changes
    if (!change) throw new Error("Expected a change")

    const cleared = clearedChange(change)

    expect(cleared.targets.add_locations).toEqual([])
    expect(addTarget([cleared], "add_locations", LEEDS)[0]?.targets.add_locations).toHaveLength(1)
  })
})

describe("inputs", () => {
  it("reads a bid adjustment only inside Google's range", () => {
    expect(parseBidAdjustment("+15%")).toBe(15)
    expect(parseBidAdjustment("-90")).toBe(-90)
    expect(parseBidAdjustment("-91")).toBeNull()
    expect(parseBidAdjustment("901")).toBeNull()
    expect(parseBidAdjustment("1.5")).toBeNull()
  })

  it("splits a paste by Google's 25 names and the route's 500 characters", () => {
    const short = Array.from({ length: 60 }, (_, index) => `L${String(index)}`)
    expect(pasteBatches(short).map((batch) => batch.length)).toEqual([25, 25, 10])

    const long = Array.from({ length: 12 }, (_, index) => `${"x".repeat(49)}${String(index)}`)
    for (const batch of pasteBatches(long)) {
      expect(batch.join("\n").length).toBeLessThanOrEqual(500)
    }

    expect(pasteBatches(["x".repeat(600), "Leeds"])).toEqual([["Leeds"]])
  })
})

const window = (
  day: ScheduleWindow["day"],
  start: string,
  end: string,
  bid: number | null = null
) => ({
  bidAdjustment: bid,
  day,
  end,
  start,
})

describe("devices and ad schedule", () => {
  it("sends devices and the whole week in the server's shape, and counts the week once", () => {
    const args = parsed()
    const devices = setDevice(
      setDevice(args.changes, "MOBILE", { bidAdjustment: -30, excluded: false }),
      "TABLET",
      { bidAdjustment: 0, excluded: true }
    )
    const next = setSchedule(devices, [
      window("MONDAY", "07:00", "22:00"),
      window("TUESDAY", "07:00", "22:00", 10),
    ])

    const [entry] = serializeChanges(next)
    expect(entry?.["devices"]).toEqual([
      { device: "MOBILE", bid_adjustment: -30 },
      { device: "TABLET", excluded: true },
    ])
    expect(entry?.["ad_schedule"]).toEqual([
      { day: "MONDAY", start: "07:00", end: "22:00", bid_adjustment: null },
      { day: "TUESDAY", start: "07:00", end: "22:00", bid_adjustment: 10 },
    ])
    expect(next[0] && itemCount(next[0])).toBe(4)
    expect(serializeChanges(setSchedule(next, "clear"))[0]).toMatchObject({
      ad_schedule: null,
      clear_ad_schedule: true,
    })
  })

  it("reads quarter hours, and flags windows that overlap but not ones that touch", () => {
    expect(["7", "7:30", "0745", "24:00", "7:10", "24:15"].map(parseTime)).toEqual([
      "07:00",
      "07:30",
      "07:45",
      "24:00",
      null,
      null,
    ])
    const rows = scheduleRows([
      ...["MONDAY", "TUESDAY"].map((day) => window(day as "MONDAY", "07:00", "12:00")),
      window("MONDAY", "12:00", "14:00", 10),
      window("TUESDAY", "11:45", "14:00", 10),
    ])
    expect(rows.map((row) => row.days.length)).toEqual([2, 1, 1])
    expect(scheduleProblems(rows)).toEqual([
      "Overlaps another window on Tue.",
      null,
      "Overlaps another window on Tue.",
    ])
  })

  it("keeps a new window as its own row even when its times match another's", () => {
    const weekdays = scheduleRows([
      window("MONDAY", "09:00", "17:00"),
      window("TUESDAY", "09:00", "17:00"),
    ])
    const added = [
      ...weekdays,
      { ...window("SATURDAY", "09:00", "17:00"), days: ["SATURDAY" as const] },
    ]

    expect(keptRows(added, rowWindows(added))).toHaveLength(2)
    // A change from outside the editor regroups the windows.
    expect(keptRows(added, [window("MONDAY", "09:00", "17:00")])).toBeNull()
  })

  it("words the week in a line, grouping days that share their windows", () => {
    const weekdays = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"] as const
    expect(
      scheduleText([
        ...weekdays.map((day) => window(day, "07:00", "22:00")),
        window("SATURDAY", "09:00", "17:00", -20),
      ])
    ).toBe("Mon–Fri 07:00–22:00; Sat 09:00–17:00 (-20%)")
    expect(scheduleText([])).toBe("Any time, every day")
  })

  it("blocks approval while windows overlap", () => {
    const args = parsed()
    const changes = setSchedule(args.changes, [
      window("MONDAY", "07:00", "12:00"),
      window("MONDAY", "11:00", "14:00"),
    ])
    expect(targetingBlock({ ...args, changes }, args)).toContain("no windows overlap")
  })

  it("refuses the same window twice on one day, and shows it as two rows", () => {
    const twice = [window("MONDAY", "09:00", "17:00"), window("MONDAY", "09:00", "17:00")]

    expect(scheduleValid(twice)).toBe(false)
    expect(scheduleProblems(scheduleRows(twice)).every((problem) => problem !== null)).toBe(true)
    expect(scheduleValid([window("MONDAY", "09:00", "17:00")])).toBe(true)
  })
})

const adGroupKey = (id: string) => `customers/${CUSTOMER}/adGroups/${id}`

function adGroupArgs(): Record<string, unknown> {
  return raw({
    changes: [
      {
        campaign: campaign("10"),
        add_locations: [{ key: "1006", name: "Manchester" }],
      },
      {
        ad_group: { customer_id: CUSTOMER, campaign_id: "10", ad_group_id: "20", label: "Shoes" },
        demographics: [{ dimension: "AGE_RANGE", value: "AGE_RANGE_18_24", excluded: true }],
      },
    ],
    _checks: {
      entries: {
        [key("10")]: check(),
        [adGroupKey("20")]: check({
          campaign_name: "Trail",
          demographics: [
            { dimension: "AGE_RANGE", value: "AGE_RANGE_65_UP", excluded: true, bid_adjustment: 0 },
          ],
          locations: [],
          languages: [],
        }),
      },
      names: { locations: { "1006": "Manchester" }, languages: {}, audiences: {} },
    },
  })
}

describe("audiences and demographics", () => {
  it("keeps campaign settings off ad group entries", () => {
    const args = parsed(adGroupArgs())

    const next = setDevice(args.changes, "MOBILE", { bidAdjustment: -30, excluded: false })

    // The server refuses devices on an ad group, so the card never sends them there.
    const [campaignEntry, adGroupEntry] = serializeChanges(next)
    expect(campaignEntry?.["devices"]).toEqual([{ device: "MOBILE", bid_adjustment: -30 }])
    expect(adGroupEntry?.["devices"]).toBeUndefined()
  })

  it("moves an audience out of the removals, and drops an entry left with nothing", () => {
    const args = parsed(adGroupArgs())
    const shoes = { bidAdjustment: 20, key: "80432", kind: "user_interest" as const, name: "Shoes" }
    const [, adGroup] = args.changes
    if (!adGroup) throw new Error("Expected the ad group")
    const removing = parsed({
      ...adGroupArgs(),
      changes: [{ ...adGroup.entry, remove_audiences: [{ kind: "user_interest", key: "80432" }] }],
    })

    const added = addAudience(removing.changes, shoes)

    expect(added[0]?.removeAudiences).toEqual([])
    expect(serializeChanges(added)[0]?.["add_audiences"]).toEqual([
      { kind: "user_interest", key: "80432", name: "Shoes", bid_adjustment: 20 },
    ])
    const onlyMode = cancelAudience(
      setDemographic(setAudienceMode(added, "OBSERVATION"), "AGE_RANGE", "AGE_RANGE_18_24", null),
      "add_audiences",
      "user_interest:80432"
    )
    expect(onlyMode).toHaveLength(1)
    expect(setAudienceMode(onlyMode, null)).toEqual([])
  })

  it("reads an excluded value as excluded now, and what the request asks for", () => {
    const args = parsed(adGroupArgs())
    const shown = { ...args, changes: args.changes.slice(1) }

    const lines = demographicLines(shown, "AGE_RANGE")

    expect(lines.find((line) => line.value === "AGE_RANGE_65_UP")?.now).toBe(EXCLUDED)
    expect(lines.find((line) => line.value === "AGE_RANGE_18_24")?.requested).toEqual({
      bidAdjustment: 0,
      dimension: "AGE_RANGE",
      excluded: true,
      value: "AGE_RANGE_18_24",
    })
  })
})

describe("presenters", () => {
  const html = (node: ReactNode) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement("div", null, node)
      )
    )
  const props = (activity: ToolActivity, withApproval = false) => ({
    activity,
    ...(withApproval
      ? {
          approvalDecision: {
            decision: { decision: "pending" as const, edits: {}, message: "" as const },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  })

  it("renders the approval and the result", () => {
    const approval = html(
      googleAdsUpdateTargetingPresenter.render(
        props(
          {
            id: "targeting-1",
            kind: "approval",
            name: "google_ads_update_targeting",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Add Manchester")

    const timed = {
      ...raw(),
      changes: [
        {
          campaign: campaign("10"),
          devices: [{ device: "MOBILE", bid_adjustment: -30 }],
          ad_schedule: [{ day: "MONDAY", start: "07:00", end: "22:00" }],
        },
      ],
    }
    const schedule = html(
      googleAdsUpdateTargetingPresenter.render(
        props(
          {
            id: "targeting-3",
            kind: "approval",
            name: "google_ads_update_targeting",
            status: "awaiting_approval",
            args: timed,
          },
          true
        )
      )
    )
    expect(schedule).toContain('role="img"')

    const audiences = html(
      googleAdsUpdateTargetingPresenter.render(
        props(
          {
            id: "targeting-4",
            kind: "approval",
            name: "google_ads_update_targeting",
            status: "awaiting_approval",
            args: adGroupArgs(),
          },
          true
        )
      )
    )
    expect(audiences).toContain('aria-label="Age"')

    const result = html(
      googleAdsUpdateTargetingPresenter.render(
        props({
          id: "targeting-2",
          kind: "result",
          name: "google_ads_update_targeting",
          status: "completed",
          args: raw(),
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: CUSTOMER,
                status: "success",
                data: {
                  account_id: CUSTOMER,
                  outcomes: [
                    {
                      campaign_id: "10",
                      campaign_name: "Trail",
                      setting: "locations",
                      action: "add",
                      outcome: "updated",
                      count: 1,
                      items: [{ name: "Manchester", bid_adjustment: 15 }],
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Manchester (+15%)")
  })

  it("renders search results", () => {
    const rendered = html(
      googleAdsSearchTargetingPresenter.render(
        props({
          id: "targeting-3",
          kind: "result",
          name: "google_ads_search_targeting",
          status: "completed",
          args: { kind: "location", names: ["Manchester"] },
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: CUSTOMER,
                status: "success",
                data: {
                  options: [
                    {
                      kind: "location",
                      key: "1006",
                      name: "Manchester",
                      target_type: "City",
                      region: "England, United Kingdom",
                      reach: 2_900_000,
                    },
                  ],
                  truncated: false,
                },
              },
            ],
          },
        })
      )
    )
    expect(rendered).toContain("2.9M")
  })
})
