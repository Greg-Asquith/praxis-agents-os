// apps/web/src/integrations/google_ads/lib/invoices.ts

import type { DataRow, DataTableTab } from "@/components/ui/data-table"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isNullableString, isOneOf, isRecord } from "@/lib/guards"

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const STATES = new Set(["listed", "not_monthly_invoicing", "manager_account"] as const)
const TYPES = new Set(["invoice", "credit_memo", "unknown"] as const)
const MONTH = /^\d{4}-\d{2}/
// Invoice numbers go into the operator's own turn, so only plain ones are accepted.
const INVOICE_ID = /^[\w.-]{1,64}$/
// Short enough to send as one turn.
export const MAX_SAVE_INVOICES = 100

export type GoogleAdsInvoice = {
  accountNames: string[]
  adjustments: string
  billingSetupId: string | null
  currency: string
  dueDate: string | null
  id: string
  issueDate: string | null
  pdfError: string | null
  pdfHref: string | null
  purchaseOrders: string[]
  serviceEnd: string | null
  serviceStart: string | null
  subtotal: string
  tax: string
  total: string
  type: "invoice" | "credit_memo" | "unknown"
}

export type GoogleAdsInvoices = {
  billingSetups: { id: string; label: string }[]
  customerId: string
  endMonth: string
  invoices: GoogleAdsInvoice[]
  startMonth: string
  state: "listed" | "not_monthly_invoicing" | "manager_account"
  truncated: boolean
}

function parsePdfHref(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null
  const file = isRecord(value) ? value["file"] : null
  const fileId = isRecord(file) ? file["entity_id"] : null
  return typeof fileId === "string" && FILE_ID.test(fileId) ? `/files?fileId=${fileId}` : undefined
}

function lineTexts(lines: unknown, key: string): string[] {
  if (!Array.isArray(lines)) return []
  const texts = lines.flatMap((line: unknown) => {
    const text = isRecord(line) ? line[key] : null
    return typeof text === "string" && text ? [text] : []
  })
  return [...new Set(texts)]
}

function parseInvoice(value: unknown): GoogleAdsInvoice | null {
  if (!isRecord(value)) return null
  const { currency, invoice_id: id, subtotal, tax, total, type } = value
  const adjustments = isRecord(value["adjustments"]) ? value["adjustments"]["total"] : null
  const pdfHref = parsePdfHref(value["pdf"])
  const dates = [
    value["billing_setup_id"],
    value["due_date"],
    value["issue_date"],
    value["pdf_error"] ?? null,
    value["service_end"],
    value["service_start"],
  ]
  if (
    typeof id !== "string" ||
    !INVOICE_ID.test(id) ||
    typeof currency !== "string" ||
    typeof subtotal !== "string" ||
    typeof tax !== "string" ||
    typeof total !== "string" ||
    typeof adjustments !== "string" ||
    !isOneOf(TYPES, type) ||
    pdfHref === undefined ||
    !dates.every(isNullableString)
  )
    return null
  const [billingSetupId, dueDate, issueDate, pdfError, serviceEnd, serviceStart] = dates
  return {
    accountNames: lineTexts(value["budget_lines"], "account_name"),
    adjustments,
    billingSetupId: billingSetupId ?? null,
    currency,
    dueDate: dueDate ?? null,
    id,
    issueDate: issueDate ?? null,
    pdfError: pdfError ?? null,
    pdfHref,
    purchaseOrders: lineTexts(value["budget_lines"], "purchase_order_number"),
    serviceEnd: serviceEnd ?? null,
    serviceStart: serviceStart ?? null,
    subtotal,
    tax,
    total,
    type,
  }
}

function parseSetup(value: unknown): GoogleAdsInvoices["billingSetups"][number] | null {
  return isRecord(value) &&
    typeof value["billing_setup_id"] === "string" &&
    typeof value["label"] === "string"
    ? { id: value["billing_setup_id"], label: value["label"] }
    : null
}

function parseAll<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null
  const parsed = value.map(parse).filter((item) => item !== null)
  return parsed.length === value.length ? parsed : null
}

export function parseGoogleAdsInvoices(value: unknown): GoogleAdsInvoices | null {
  if (!isRecord(value)) return null
  const { customer_id: customerId, end_month: endMonth, start_month: startMonth, state } = value
  const invoices = parseAll(value["invoices"], parseInvoice)
  const billingSetups = parseAll(value["billing_setups"], parseSetup)
  if (
    typeof customerId !== "string" ||
    typeof startMonth !== "string" ||
    typeof endMonth !== "string" ||
    !isOneOf(STATES, state) ||
    !invoices ||
    !billingSetups
  )
    return null
  return {
    billingSetups,
    customerId,
    endMonth,
    invoices,
    startMonth,
    state,
    truncated: value["truncated"] === true,
  }
}

/** The month an invoice bills, such as "October 2026", from its service period. */
export function invoiceMonthLabel(invoice: GoogleAdsInvoice): string {
  const month = invoice.serviceStart ?? invoice.issueDate
  if (!month || !MONTH.test(month)) return "Unknown"
  const date = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1))
  return new Intl.DateTimeFormat("en-GB", {
    month: "long",
    timeZone: "UTC",
    year: "numeric",
  }).format(date)
}

/** A tab per billing setup when invoices come from several, then Credit Memos. */
export function invoiceTabs(result: GoogleAdsInvoices): DataTableTab[] {
  const used = new Set(result.invoices.map((invoice) => invoice.billingSetupId))
  const setups = result.billingSetups.filter((setup) => used.has(setup.id))
  const credits = result.invoices.some((invoice) => invoice.type === "credit_memo")
  if (setups.length < 2 && !credits) return []
  return [
    { id: "all", label: "All", match: () => true },
    ...(setups.length > 1
      ? setups.map((setup) => ({
          id: `setup:${setup.id}`,
          label: setup.label,
          match: (row: DataRow) => row["billing_setup_id"] === setup.id,
        }))
      : []),
    {
      hideWhenEmpty: true,
      id: "credits",
      label: "Credit Memos",
      match: (row: DataRow) => row["type_token"] === "credit_memo",
    },
  ]
}

/** What the card sends as the operator's own turn to save the chosen invoices' PDFs.

Carries only Google's invoice numbers and the months they were issued in.
 */
export function savePdfsInstruction(
  result: GoogleAdsInvoices,
  invoices: readonly GoogleAdsInvoice[]
): string {
  const months = invoices
    .map((invoice) => invoice.issueDate?.slice(0, 7))
    .filter((month): month is string => month !== undefined && MONTH.test(month))
    .sort()
  const from = months[0] ?? result.startMonth
  const to = months.at(-1) ?? result.endMonth
  return [
    `Save the PDFs of these ${String(invoices.length)} Google Ads invoices from account ` +
      `${formatGoogleAdsAccountId(result.customerId)} to Files. ` +
      `They were issued from ${from} to ${to}.`,
    ...invoices.map((invoice) => `- ${invoice.id}`),
  ].join("\n")
}
