// apps/web/src/integrations/google_ads/components/invoices-table.tsx

import { useMemo, useState } from "react"

import { useInstructionAction } from "@/components/tool-ui/conversation-actions-context"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableSelection,
} from "@/components/ui/data-table"
import {
  invoiceMonthLabel,
  invoiceTabs,
  MAX_SAVE_INVOICES,
  savePdfsInstruction,
  type GoogleAdsInvoices,
} from "@/integrations/google_ads/lib/invoices"
import { formatCurrencyAmount } from "@/lib/format"

const COLUMNS: DataColumn[] = [
  { key: "month", kind: "text", label: "Month", width: 150 },
  { key: "billing_setup", kind: "text", label: "Billing Setup" },
  { key: "invoice", kind: "id", label: "Invoice" },
  { key: "type", kind: "text", label: "Type" },
  { align: "right", key: "total", kind: "number", label: "Amount" },
  { key: "due", kind: "date", label: "Due" },
  { key: "pdf", kind: "text", label: "PDF" },
  { hidden: true, key: "issued", kind: "date", label: "Issued" },
  { hidden: true, key: "service_period", kind: "text", label: "Service Period" },
  { align: "right", hidden: true, key: "subtotal", kind: "number", label: "Before Tax" },
  { align: "right", hidden: true, key: "tax", kind: "number", label: "Tax" },
  { align: "right", hidden: true, key: "adjustments", kind: "number", label: "Adjustments" },
  { hidden: true, key: "currency", kind: "text", label: "Currency" },
  { hidden: true, key: "purchase_orders", kind: "text", label: "Purchase Orders" },
  { hidden: true, key: "accounts", kind: "text", label: "Accounts" },
]
const MONEY_KEYS = new Set(["total", "subtotal", "tax", "adjustments"])
const TYPE_LABELS = { credit_memo: "Credit Memo", invoice: "Invoice", unknown: "Other" } as const
const INVOICE_NOUN = ["invoice", "invoices"] as const

function renderCell(column: DataColumn, row: DataRow) {
  if (column.key === "type" && row["type_token"] === "credit_memo") {
    return <Badge variant="outline">Credit Memo</Badge>
  }
  if (column.key === "pdf") {
    const href = row["pdf_href"]
    if (typeof href === "string") {
      return (
        <a className="text-link hover:text-primary underline underline-offset-2" href={href}>
          Open in Files
        </a>
      )
    }
    return <span className="text-muted-foreground">{String(row["pdf"])}</span>
  }
  if (!MONEY_KEYS.has(column.key)) return null
  const value = row[column.key]
  const currency = row["currency"]
  if (typeof value !== "string" || typeof currency !== "string") return null
  return <span className="tabular-nums">{formatCurrencyAmount(value, currency)}</span>
}

/** One account's invoices; selected rows start a governed turn that saves their PDFs to Files.

`preview` is true while only the first rows of a large result have loaded, so nothing is saved
from a partial list.
 */
export function GoogleAdsInvoicesTable({
  preview,
  result,
}: {
  preview: boolean
  result: GoogleAdsInvoices
}) {
  const { available, error, send, sending } = useInstructionAction()
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const rows = useMemo(() => {
    const setups = new Map(result.billingSetups.map((setup) => [setup.id, setup.label]))
    return result.invoices.map((invoice) => ({
      accounts: invoice.accountNames.join(", "),
      adjustments: invoice.adjustments,
      billing_setup: invoice.billingSetupId ? (setups.get(invoice.billingSetupId) ?? null) : null,
      billing_setup_id: invoice.billingSetupId,
      currency: invoice.currency,
      due: invoice.dueDate,
      invoice: invoice.id,
      issued: invoice.issueDate,
      month: invoiceMonthLabel(invoice),
      pdf: invoice.pdfHref ? "Saved to Files" : (invoice.pdfError ?? "Not in Files"),
      pdf_href: invoice.pdfHref,
      purchase_orders: invoice.purchaseOrders.join(", "),
      service_period:
        invoice.serviceStart && invoice.serviceEnd
          ? `${invoice.serviceStart} to ${invoice.serviceEnd}`
          : null,
      subtotal: invoice.subtotal,
      tax: invoice.tax,
      total: invoice.total,
      type: TYPE_LABELS[invoice.type],
      type_token: invoice.type,
    }))
  }, [result.billingSetups, result.invoices])
  const tabs = useMemo(() => invoiceTabs(result), [result])
  const chosen = result.invoices.filter((invoice) => selected.has(invoice.id))
  const tooMany = chosen.length > MAX_SAVE_INVOICES

  async function handleSave() {
    if (await send(savePdfsInstruction(result, chosen))) setSelected(new Set())
  }

  const selection: DataTableSelection | null =
    preview || result.invoices.every((invoice) => invoice.pdfHref)
      ? null
      : {
          actions: (
            <>
              {tooMany ? (
                <span className="text-muted-foreground text-xs">
                  Select up to {String(MAX_SAVE_INVOICES)} invoices to save at once.
                </span>
              ) : null}
              {error ? <span className="text-destructive text-xs">{error}</span> : null}
              <Button
                disabled={!available || sending || tooMany}
                onClick={() => {
                  void handleSave()
                }}
                size="sm"
                type="button"
              >
                Save {chosen.length.toLocaleString("en-GB")} PDFs to Files
              </Button>
            </>
          ),
          onChange: setSelected,
          rowId: (row) => String(row["invoice"]),
          selected,
        }

  return (
    <DataTable
      columns={COLUMNS}
      exportFilename={`google-ads-${result.customerId}-invoices.csv`}
      pageSize={25}
      renderCell={renderCell}
      rowNoun={INVOICE_NOUN}
      rows={rows}
      searchable={rows.length > 10}
      {...(selection ? { selection } : {})}
      summary={<span>Amounts are in each invoice&apos;s currency, as Google bills them.</span>}
      tabs={tabs}
      truncationNote={
        result.truncated && !preview
          ? `These are the ${result.invoices.length.toLocaleString("en-GB")} most recent invoices. List fewer months to get the rest.`
          : null
      }
    />
  )
}
