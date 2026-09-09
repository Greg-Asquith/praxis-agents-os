import { createElement, type ComponentProps } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type * as DataTableModule from "@/components/ui/data-table"
import type { DataTable } from "@/components/ui/data-table"
import { dataTableExport } from "@/components/ui/data-table-model"
import googleAdsModule from "@/integrations/google_ads"
import { tableToCsv } from "@/lib/table-export"

const captured = vi.hoisted(() => ({ tables: [] as ComponentProps<typeof DataTable>[] }))
vi.mock("@/components/ui/data-table", async (importOriginal) => {
  const original = await importOriginal<typeof DataTableModule>()
  return {
    ...original,
    DataTable: (props: ComponentProps<typeof DataTable>) => {
      captured.tables.push(props)
      return createElement(original.DataTable, props)
    },
  }
})

const budget = {
  budget_id: "55",
  customer_id: "1234567890",
  label: "Requested budget",
  currency_code: "GBP",
  period: "DAILY",
  amount_micros: 10000000,
  total_amount_micros: null,
  reference_count: 0,
  campaign_labels: [],
  status: "ENABLED",
  explicitly_shared: false,
  delivery_method: "STANDARD",
}
const campaign = { campaign_id: "10", customer_id: "1234567890", label: "Search" }
const keyword = { text: "running shoes", match_type: "EXACT" }
const cases = [
  {
    name: "google_ads_assign_campaign_budgets",
    applied: "assigned",
    skipped: "already_set",
    metadata: { destination_budget: budget },
    sample: {
      campaign,
      previous_budget: { ...budget, label: "Previous budget" },
      requested_budget: budget,
    },
    column: "Campaign",
    label: "Search",
  },
  {
    name: "google_ads_remove_campaign_budgets",
    applied: "removed",
    metadata: {},
    sample: { reference: budget, previous_status: "ENABLED", resulting_status: "REMOVED" },
    column: "Budget",
    label: "Requested budget",
  },
  {
    name: "google_ads_update_campaign_budget_amounts",
    applied: "updated",
    skipped: "already_set",
    metadata: { campaign_labels_truncated: false },
    sample: {
      reference: budget,
      previous_amount: "10",
      requested_amount: "15",
      campaign_label_count: 0,
      campaign_labels_truncated: false,
    },
    column: "Budget",
    label: "Requested budget",
  },
  {
    name: "google_ads_create_keywords",
    applied: "added",
    skipped: "skipped_existing",
    metadata: { currency_code: "GBP" },
    sample: {
      campaign_id: "10",
      campaign_name: "Search",
      ad_group_id: "20",
      ad_group_name: "Shoes",
      requested: keyword,
      observed: null,
      previous_state: "absent",
    },
    column: "Keyword",
    label: "running shoes",
  },
  {
    name: "google_ads_add_negative_keywords",
    applied: "added",
    skipped: "skipped_existing",
    metadata: {},
    sample: {
      ...keyword,
      resource_name: "customers/123/sharedCriteria/1",
      scope: "keyword",
      message: "Rejected keyword",
    },
    column: "Keyword",
    label: "running shoes",
  },
  {
    name: "google_ads_remove_negative_keywords",
    applied: "removed",
    skipped: "not_found",
    metadata: {},
    sample: {
      ...keyword,
      resource_name: "customers/123/sharedCriteria/1",
      scope: "keyword",
      message: "Rejected keyword",
    },
    column: "Keyword",
    label: "running shoes",
  },
]

const expectedCsv: Record<string, string> = {
  google_ads_assign_campaign_budgets:
    "Campaign,Campaign ID,Before,Requested,After,Outcome\r\nSearch,10,Previous budget,Requested budget,Requested budget,Assigned",
  google_ads_remove_campaign_budgets:
    "Budget,Budget ID,Amount,Period,Linked Campaigns,Before,After,Outcome\r\nRequested budget,55,£10.00,Daily,0 campaigns,Enabled,Removed,Removed",
  google_ads_update_campaign_budget_amounts:
    "Budget,Before,Requested,After,Requested change,Period,Linked Campaigns,Outcome,Details\r\nRequested budget,£10.00,£15.00,£15.00,+50%,Daily,0 campaigns,Updated,Requested: £456.00 estimated per month",
  google_ads_create_keywords:
    "Campaign,Ad Group,Keyword,Match Type,Requested Status,Existing Status,Requested Bid,Existing Bid,Requested URLs,Existing URLs,Previous State,Outcome\r\nSearch,Shoes,running shoes,Exact,Enabled,—,Ad group default,—,None,—,Not present,Added",
  google_ads_add_negative_keywords: "Keyword,Match Type,Outcome\r\nrunning shoes,EXACT,Added",
  google_ads_remove_negative_keywords: "Keyword,Match Type,Outcome\r\nrunning shoes,EXACT,Removed",
}

type Case = (typeof cases)[number]
function envelope(test: Case, truncated = false) {
  const outcomes = [
    test.applied,
    ...(test.skipped ? [test.skipped] : []),
    "failed",
    ...(test.name.includes("negative_keywords") ? [] : ["unverified"]),
  ]
  return {
    ...test.metadata,
    counts: Object.fromEntries(
      outcomes.map((outcome) => [outcome, outcome === test.applied ? 1 : 0])
    ),
    samples: Object.fromEntries(
      outcomes.map((outcome) => [
        outcome,
        outcome === test.applied ? [{ ...test.sample, outcome }] : [],
      ])
    ) as Record<string, Record<string, unknown>[]>,
    samples_truncated: truncated,
  }
}
function render(name: string, data: unknown) {
  const activity = {
    id: "result",
    kind: "approval" as const,
    name,
    status: "completed" as const,
    args: null,
    result: {
      results: [
        {
          data,
          display_name: "Client account",
          external_id: "1234567890",
          provider_key: "google_ads",
          status: "success",
          error_message: null,
        },
      ],
    },
  }
  const presenter = googleAdsModule.toolRowPresenters.find((candidate) =>
    candidate.matches(activity)
  )
  if (!presenter) throw new Error(`Missing presenter: ${name}`)
  return renderToStaticMarkup(
    createElement(
      "div",
      null,
      presenter.render({
        activity,
        compact: false,
        defaultOpen: true,
        live: false,
        providerKey: "google_ads",
      })
    )
  )
}

beforeEach(() => {
  captured.tables = []
})
describe.each(cases)("$name result evidence", (test) => {
  it.each(["wrong outcome", "missing complete samples", "excess truncated samples"])(
    "rejects %s",
    (defect) => {
      const data = envelope(test, defect === "excess truncated samples")
      if (defect === "missing complete samples") data.samples[test.applied] = []
      else {
        data.counts[test.applied] = 0
        data.counts["failed"] = 1
      }
      expect(render(test.name, data)).toContain("couldn&#x27;t verify this account&#x27;s")
      expect(captured.tables).toHaveLength(0)
    }
  )
  it.each([false, true])("preserves valid evidence and exports (truncated: %s)", (truncated) => {
    const data = envelope(test, truncated)
    if (truncated) data.counts[test.applied] = 3
    const html = render(test.name, data)
    expect(html).not.toContain("couldn&#x27;t verify this account&#x27;s")
    expect(html).toContain(test.label)
    expect(captured.tables).toHaveLength(1)
    const table = captured.tables[0]
    if (!table) throw new Error("Expected an outcome table")
    const exported = dataTableExport(table.columns, table.rows)
    expect(exported.headers).toContain(test.column)
    expect(exported.rows).toHaveLength(1)
    const appliedLabel =
      test.applied === "assigned"
        ? "Assigned"
        : test.applied === "updated"
          ? "Updated"
          : test.applied === "removed"
            ? "Removed"
            : "Added"
    const skippedLabel =
      test.skipped === "already_set"
        ? "Already set"
        : test.skipped === "not_found"
          ? "Not found"
          : "Already existed"
    const stats = renderToStaticMarkup(createElement("div", null, table.header))
    const statValues = [...stats.matchAll(/>([^<>]+)<\/div>/g)].map((match) => match[1])
    expect(statValues.join("")).toBe(
      `${appliedLabel}${truncated ? "3" : "1"}${test.skipped ? `${skippedLabel}0` : ""}Failed0${test.name.includes("negative_keywords") ? "" : "Unverified0"}`
    )
    expect(exported.rows[0]?.[exported.headers.indexOf(test.column)]).toBe(test.label)
    expect(exported.rows[0]?.[exported.headers.indexOf("Outcome")]).toBe(appliedLabel)
    expect(tableToCsv(exported)).toBe(expectedCsv[test.name])
    expect(html.includes("Showing a representative sample.")).toBe(truncated)
  })
})

describe("budget requested and confirmed values", () => {
  it.each(cases.filter((test) => test.applied === "assigned" || test.applied === "updated"))(
    "separates mixed outcomes in $name cells and CSV",
    (test) => {
      const data = envelope(test)
      for (const outcome of [test.applied, "already_set", "failed", "unverified"]) {
        data.counts[outcome] = 1
        data.samples[outcome] = [{ ...test.sample, outcome }]
      }
      const html = render(test.name, data)
      const table = captured.tables[0]
      if (!table) throw new Error("Expected an outcome table")
      const exported = dataTableExport(table.columns, table.rows)
      expect(exported.headers).toEqual(
        test.applied === "assigned"
          ? ["Campaign", "Campaign ID", "Before", "Requested", "After", "Outcome", "Error code"]
          : [
              "Budget",
              "Before",
              "Requested",
              "After",
              "Requested change",
              "Period",
              "Linked Campaigns",
              "Outcome",
              "Details",
              "Error code",
            ]
      )
      const before = exported.headers.indexOf("Before")
      const requested = exported.headers.indexOf("Requested")
      const after = exported.headers.indexOf("After")
      const previousValue = test.applied === "assigned" ? "Previous budget" : "£10.00"
      const requestedValue = test.applied === "assigned" ? "Requested budget" : "£15.00"
      expect(exported.rows.map((row) => [row[before], row[requested], row[after]])).toEqual([
        [previousValue, requestedValue, requestedValue],
        [previousValue, requestedValue, requestedValue],
        [previousValue, requestedValue, "Unconfirmed"],
        [previousValue, requestedValue, "Unconfirmed"],
      ])
      const cells = html.match(/<td[\s\S]*?<\/td>/g) ?? []
      expect(cells.filter((cell) => cell.includes(">Unconfirmed<"))).toHaveLength(2)
      expect(cells.filter((cell) => cell.includes(`>${requestedValue}<`))).toHaveLength(6)
      const csv = tableToCsv(exported)
      expect(csv).toContain("Before,Requested,After")
      expect(csv.match(/Unconfirmed/g)).toHaveLength(2)
      if (test.applied === "updated") {
        expect(html).toContain('aria-label="Requested change: +50% from the previous amount"')
        expect(
          exported.rows.every(
            (row) => row[8]?.startsWith("Requested: ") && row[8].includes("estimated per month")
          )
        ).toBe(true)
      }
    }
  )
})

it.each(cases.filter((test) => test.name.includes("negative_keywords")))(
  "retains account-level errors in $name",
  (test) => {
    const data = envelope(test)
    data.counts["failed"] = 1
    data.samples["failed"] = [
      { scope: "account", message: "Account access denied", error_code: "AUTHORIZATION_ERROR" },
    ]
    const html = render(test.name, data)
    expect(html).toContain("Account access denied")
    expect(html).not.toContain("couldn&#x27;t verify this account&#x27;s")
    const table = captured.tables[0]
    if (!table) throw new Error("Expected an outcome table")
    expect(tableToCsv(dataTableExport(table.columns, table.rows))).toContain(
      "Account access denied"
    )
  }
)
