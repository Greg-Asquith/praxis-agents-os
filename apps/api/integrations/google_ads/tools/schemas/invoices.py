# apps/api/integrations/google_ads/tools/schemas/invoices.py

"""Result contract for Google Ads invoices, with exact amounts in the invoice currency."""

from typing import Annotated, Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput
from services.integrations.files import FileReference

from ...operations.list_invoices import (
    MAX_INVOICE_CREDITS,
    MAX_INVOICE_LINES,
    MAX_INVOICE_SETUPS,
    MAX_INVOICES,
)
from ...references import GoogleAdsBillingSetupReference
from .accounts import GoogleAdsMoney, GoogleAdsText
from .base import GoogleAdsStrictModel

type GoogleAdsInvoiceMonth = Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
type _Date = Annotated[str, Field(max_length=10)]
type _Id = Annotated[str, Field(max_length=64)]


class GoogleAdsInvoiceAmounts(GoogleAdsStrictModel):
    # Before tax, the tax, and the two together. Credits are negative.
    subtotal: GoogleAdsMoney
    tax: GoogleAdsMoney
    total: GoogleAdsMoney


class GoogleAdsInvalidActivityCredit(GoogleAdsStrictModel):
    amount: GoogleAdsMoney
    original_invoice_id: GoogleAdsText | None
    original_month: GoogleAdsInvoiceMonth | None
    original_account_budget_name: GoogleAdsText | None
    original_purchase_order_number: GoogleAdsText | None


class GoogleAdsInvoiceBudgetLine(GoogleAdsInvoiceAmounts):
    """What one account spending limit was billed on this invoice."""

    customer_id: _Id | None
    account_name: GoogleAdsText | None
    account_budget_id: _Id | None
    account_budget_name: GoogleAdsText | None
    purchase_order_number: GoogleAdsText | None
    activity_start: _Date | None
    activity_end: _Date | None
    # Spend served in the service period, for checking against reports.
    served: GoogleAdsMoney
    billed: GoogleAdsMoney
    overdelivery: GoogleAdsMoney
    invalid_activity: GoogleAdsMoney
    invalid_activity_credits: list[GoogleAdsInvalidActivityCredit] = Field(
        max_length=MAX_INVOICE_CREDITS
    )


class GoogleAdsInvoiceAccountLine(GoogleAdsInvoiceAmounts):
    """One account's adjustments and total on this invoice."""

    customer_id: _Id | None
    billing_corrections: GoogleAdsInvoiceAmounts
    coupon_adjustments: GoogleAdsInvoiceAmounts
    excess_credit_adjustments: GoogleAdsInvoiceAmounts
    export_charges: GoogleAdsInvoiceAmounts
    regulatory_costs: GoogleAdsInvoiceAmounts


class GoogleAdsInvoicePdf(GoogleAdsStrictModel):
    file: FileReference
    name: str = Field(max_length=255)
    size_bytes: int = Field(ge=0)


class GoogleAdsInvoice(GoogleAdsInvoiceAmounts):
    # Google's invoice number, as printed on the PDF.
    invoice_id: _Id
    type: Literal["invoice", "credit_memo", "unknown"]
    billing_setup_id: _Id | None
    payments_account_id: GoogleAdsText | None
    payments_profile_id: GoogleAdsText | None
    issue_date: _Date | None
    due_date: _Date | None
    service_start: _Date | None
    service_end: _Date | None
    # Every amount on the invoice is in this currency, which can differ from the account's.
    currency: str = Field(max_length=3)
    adjustments: GoogleAdsInvoiceAmounts
    regulatory_costs: GoogleAdsInvoiceAmounts
    export_charges: GoogleAdsInvoiceAmounts
    # Set on an invoice that corrects, writes off, or cancels an earlier one.
    corrected_invoice_id: _Id | None
    replaced_invoice_ids: list[_Id] = Field(max_length=MAX_INVOICE_CREDITS)
    # An invoice for a shared payments account has lines for every account it covers.
    budget_lines: list[GoogleAdsInvoiceBudgetLine] = Field(max_length=MAX_INVOICE_LINES)
    account_lines: list[GoogleAdsInvoiceAccountLine] = Field(max_length=MAX_INVOICE_LINES)
    lines_truncated: bool
    # The PDF saved to Files, when save_pdf was set and Google returned it.
    pdf: GoogleAdsInvoicePdf | None
    pdf_error: GoogleAdsText | None


class GoogleAdsInvoicesData(GoogleAdsStrictModel):
    customer_id: str = Field(pattern=r"^[0-9]{1,32}$")
    # not_monthly_invoicing and manager_account aren't errors: the account gets no invoices.
    state: Literal["listed", "not_monthly_invoicing", "manager_account"]
    start_month: GoogleAdsInvoiceMonth
    end_month: GoogleAdsInvoiceMonth
    # The approved billing setups whose invoices were listed.
    billing_setups: list[GoogleAdsBillingSetupReference] = Field(max_length=MAX_INVOICE_SETUPS)
    # Newest first.
    invoices: list[GoogleAdsInvoice] = Field(max_length=MAX_INVOICES)
    truncated: bool


class GoogleAdsInvoicesEntry(IntegrationFanOutEntry):
    data: GoogleAdsInvoicesData | None = None


class GoogleAdsInvoicesOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsInvoicesEntry]
