// apps/web/tests/integrations/google-ads/list-invoices.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  invoiceTabs,
  parseGoogleAdsInvoices,
  savePdfsInstruction,
} from "@/integrations/google_ads/lib/invoices"
import { googleAdsListInvoicesPresenter } from "@/integrations/google_ads/presenters/list-invoices"

const AMOUNTS = { subtotal: "0", tax: "0", total: "0" }

function invoice(id: string, fields: Record<string, unknown> = {}) {
  return {
    invoice_id: id,
    type: "invoice",
    billing_setup_id: "71",
    payments_account_id: null,
    payments_profile_id: null,
    issue_date: "2026-11-02",
    due_date: "2026-11-30",
    service_start: "2026-10-01",
    service_end: "2026-10-31",
    currency: "GBP",
    subtotal: "3594",
    tax: "718.8",
    total: "4312.8",
    adjustments: AMOUNTS,
    regulatory_costs: AMOUNTS,
    export_charges: AMOUNTS,
    corrected_invoice_id: null,
    replaced_invoice_ids: [],
    budget_lines: [{ account_name: "Northwind Outdoor UK", purchase_order_number: "PO-4471" }],
    account_lines: [],
    lines_truncated: false,
    pdf: null,
    pdf_error: null,
    ...fields,
  }
}

const SETUP = { entity_kind: "google_ads_billing_setup", customer_id: "4821930571" }
const DATA = {
  customer_id: "4821930571",
  state: "listed",
  start_month: "2026-09",
  end_month: "2026-11",
  billing_setups: [
    { ...SETUP, billing_setup_id: "71", label: "UK Card" },
    { ...SETUP, billing_setup_id: "72", label: "Agency Credit" },
  ],
  invoices: [
    invoice("5391-0042", {
      pdf: {
        file: { entity_id: "0b6d5d0e-6c7c-4a52-9a53-0d5a0c6b7e11" },
        name: "Google Ads Invoice 5391-0042.pdf",
        size_bytes: 1200,
      },
    }),
    invoice("5391-0039", { billing_setup_id: "72", issue_date: "2026-10-03" }),
    invoice("5391-0040", { type: "credit_memo", total: "-120.5", issue_date: "2026-09-04" }),
  ],
  truncated: false,
}

describe("Google Ads invoices", () => {
  it("renders amounts in the invoice currency and links a saved PDF's File", () => {
    const html = renderToStaticMarkup(
      createElement(
        "div",
        null,
        googleAdsListInvoicesPresenter.render({
          activity: {
            id: "invoices-1",
            kind: "result",
            name: "google_ads_list_invoices",
            status: "completed",
            args: { start_month: "2026-09", end_month: "2026-11" },
            result: {
              results: [
                {
                  provider_key: "google_ads",
                  display_name: "Northwind",
                  external_id: "4821930571",
                  status: "success",
                  data: DATA,
                  error_message: null,
                },
              ],
            },
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "google_ads",
        })
      )
    )

    expect(html).toContain("£4,312.80")
    expect(html).toContain('href="/files?fileId=0b6d5d0e-6c7c-4a52-9a53-0d5a0c6b7e11"')
  })

  it("refuses a saved PDF whose File ID isn't a File's", () => {
    const [first] = DATA.invoices
    const forged = { ...first, pdf: { file: { entity_id: "../settings" } } }
    expect(parseGoogleAdsInvoices({ ...DATA, invoices: [forged] })).toBe(null)
  })

  it("makes a tab per billing setup only when invoices come from several", () => {
    const result = parseGoogleAdsInvoices(DATA)
    if (!result) throw new Error("invoices didn't parse")
    expect(invoiceTabs(result).map((tab) => tab.label)).toEqual([
      "All",
      "UK Card",
      "Agency Credit",
      "Credit Memos",
    ])
    const one = { ...result, invoices: result.invoices.slice(0, 1) }
    expect(invoiceTabs(one)).toEqual([])
  })

  it("asks to save the chosen invoices by number, across the months they were issued in", () => {
    const result = parseGoogleAdsInvoices(DATA)
    if (!result) throw new Error("invoices didn't parse")
    expect(savePdfsInstruction(result, result.invoices.slice(1))).toBe(
      "Save the PDFs of these 2 Google Ads invoices from account 482-193-0571 to Files. " +
        "They were issued from 2026-09 to 2026-10.\n- 5391-0039\n- 5391-0040"
    )
  })
})
