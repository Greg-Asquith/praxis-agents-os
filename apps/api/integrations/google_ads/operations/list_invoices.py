# apps/api/integrations/google_ads/operations/list_invoices.py

"""Lists the monthly invoices Google issued to one account."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..client import GoogleAdsClient, GoogleAdsRequestRejectedError
from ..tools.utils.money import micros_to_money
from .account_billing import billing_setup_reference, read_billing_setups
from .invoice_requests import (
    INVOICES_OPERATION,
    MONTHS,
    list_invoice_month,
    refused_as_not_invoiced,
)

MAX_INVOICEMONTHS = 12
MAX_INVOICES = 500
MAX_INVOICE_LINES = 1_000
MAX_INVOICE_CREDITS = 100
# A payer switch leaves earlier setups approved, and their invoices are still Google's record.
MAX_INVOICE_SETUPS = 5
# Google keeps invoices issued from January 2019.
_FIRST_MONTH = (2019, 1)
_TYPES = {"INVOICE": "invoice", "CREDIT_MEMO": "credit_memo"}


@dataclass(frozen=True, slots=True)
class InvoiceList:
    """One account's invoices, with each PDF address kept apart from the result."""

    data: dict[str, Any]
    # By invoice ID. Google's addresses need the bearer token, so they never reach the model.
    pdf_urls: dict[str, str]


def invoice_months(start: str, end: str, *, today: date) -> list[tuple[int, int]]:
    """Returns each issue month from `start` to `end`, both `YYYY-MM` and inclusive.

    Raises:
        ValueError: With copy for the agent when the range is backwards, starts before Google
            keeps invoices, ends after this month, or covers more than 12 months.
    """
    first = _month(start)
    last = _month(end)
    if last < first:
        raise ValueError("end_month must be the same as or later than start_month.")
    if first < _FIRST_MONTH:
        raise ValueError("Google Ads only keeps invoices issued from 2019-01.")
    if last > (today.year, today.month):
        raise ValueError("end_month can't be later than this month.")
    count = (last[0] - first[0]) * 12 + last[1] - first[1] + 1
    if count > MAX_INVOICEMONTHS:
        raise ValueError(
            f"List at most {MAX_INVOICEMONTHS} months in one call. Call again for the rest."
        )
    return [divmod(first[0] * 12 + first[1] - 1 + offset, 12) for offset in range(count)]


async def list_invoices(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    account_name: str,
    login_customer_id: str,
    months: Sequence[tuple[int, int]],
    max_response_bytes: int,
) -> InvoiceList:
    """Reads every invoice issued in `months` for the account's approved billing setups.

    `months` holds (year, zero-based month) pairs from `invoice_months`. An invoice that covers
    several accounts or comes back for two months is kept once. An account with no approved
    setup, or whose setups get no invoices, returns `not_monthly_invoicing` with no error.

    Raises:
        IntegrationPermissionError: When this sign-in can't read the account's invoices.
    """
    setups = [
        setup
        for setup in await read_billing_setups(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            max_response_bytes=max_response_bytes,
            operation=INVOICES_OPERATION,
        )
        if setup.get("status") == "APPROVED"
    ][:MAX_INVOICE_SETUPS]
    listed: list[dict[str, Any]] = []
    found: dict[str, Mapping[str, Any]] = {}
    for setup in setups:
        reference = billing_setup_reference(
            setup, customer_id=customer_id, account_name=account_name
        )
        try:
            for year, month in months:
                payload = await list_invoice_month(
                    client,
                    customer_id=customer_id,
                    login_customer_id=login_customer_id,
                    billing_setup=reference.resource_name,
                    year=year,
                    month=month,
                    max_response_bytes=max_response_bytes,
                )
                for invoice in _mappings(_mapping(payload).get("invoices")):
                    if invoice.get("id"):
                        found.setdefault(str(invoice["id"]), invoice)
        except GoogleAdsRequestRejectedError as exc:
            if not refused_as_not_invoiced(exc):
                raise
            continue
        listed.append(reference.model_dump(mode="json"))
    newest_first = sorted(
        found.values(),
        key=lambda invoice: (str(invoice.get("issueDate") or ""), str(invoice["id"])),
        reverse=True,
    )
    kept = newest_first[:MAX_INVOICES]
    return InvoiceList(
        data={
            "customer_id": customer_id,
            "state": "listed" if listed else "not_monthly_invoicing",
            "start_month": _month_text(*months[0]),
            "end_month": _month_text(*months[-1]),
            "billing_setups": listed,
            "invoices": [_invoice(invoice) for invoice in kept],
            "truncated": len(newest_first) > len(kept),
        },
        pdf_urls={
            str(invoice["id"]): url
            for invoice in kept
            if isinstance((url := invoice.get("pdfUrl")), str) and url
        },
    )


def _invoice(invoice: Mapping[str, Any]) -> dict[str, Any]:
    service = _mapping(invoice.get("serviceDateRange"))
    budget_lines = _mappings(invoice.get("accountBudgetSummaries"))
    account_lines = _mappings(invoice.get("accountSummaries"))
    return {
        "invoice_id": str(invoice["id"]),
        "type": _TYPES.get(str(invoice.get("type")), "unknown"),
        "billing_setup_id": _last_segment(invoice.get("billingSetup")),
        "payments_account_id": _text(invoice.get("paymentsAccountId")),
        "payments_profile_id": _text(invoice.get("paymentsProfileId")),
        "issue_date": _date(invoice.get("issueDate")),
        "due_date": _date(invoice.get("dueDate")),
        "service_start": _date(service.get("startDate")),
        "service_end": _date(service.get("endDate")),
        "currency": str(invoice.get("currencyCode") or "")[:3],
        **_amounts(invoice, ""),
        "adjustments": _amounts(invoice, "adjustments"),
        "regulatory_costs": _amounts(invoice, "regulatoryCosts"),
        "export_charges": _amounts(invoice, "exportCharge"),
        "corrected_invoice_id": _last_segment(invoice.get("correctedInvoice")),
        "replaced_invoice_ids": [
            invoice_id
            for name in _list(invoice.get("replacedInvoices"))[:MAX_INVOICE_CREDITS]
            if (invoice_id := _last_segment(name))
        ],
        "budget_lines": [_budget_line(line) for line in budget_lines[:MAX_INVOICE_LINES]],
        "account_lines": [_account_line(line) for line in account_lines[:MAX_INVOICE_LINES]],
        "lines_truncated": max(len(budget_lines), len(account_lines)) > MAX_INVOICE_LINES,
        "pdf": None,
        "pdf_error": None,
    }


def _budget_line(line: Mapping[str, Any]) -> dict[str, Any]:
    activity = _mapping(line.get("billableActivityDateRange"))
    return {
        "customer_id": _last_segment(line.get("customer")),
        "account_name": _text(line.get("customerDescriptiveName")),
        "account_budget_id": _last_segment(line.get("accountBudget")),
        "account_budget_name": _text(line.get("accountBudgetName")),
        "purchase_order_number": _text(line.get("purchaseOrderNumber")),
        "activity_start": _date(activity.get("startDate")),
        "activity_end": _date(activity.get("endDate")),
        "served": _money(line.get("servedAmountMicros")),
        "billed": _money(line.get("billedAmountMicros")),
        "overdelivery": _money(line.get("overdeliveryAmountMicros")),
        "invalid_activity": _money(line.get("invalidActivityAmountMicros")),
        **_amounts(line, ""),
        "invalid_activity_credits": [
            {
                "amount": _money(credit.get("amountMicros")),
                "original_invoice_id": _text(credit.get("originalInvoiceId")),
                "original_month": _service_month(credit),
                "original_account_budget_name": _text(credit.get("originalAccountBudgetName")),
                "original_purchase_order_number": _text(credit.get("originalPurchaseOrderNumber")),
            }
            for credit in _mappings(line.get("invalidActivitySummaries"))[:MAX_INVOICE_CREDITS]
        ],
    }


def _account_line(line: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "customer_id": _last_segment(line.get("customer")),
        "billing_corrections": _amounts(line, "billingCorrection"),
        "coupon_adjustments": _amounts(line, "couponAdjustment"),
        "excess_credit_adjustments": _amounts(line, "excessCreditAdjustment"),
        "export_charges": _amounts(line, "exportCharge"),
        "regulatory_costs": _amounts(line, "regulatoryCosts"),
        **_amounts(line, ""),
    }


def _amounts(source: Mapping[str, Any], prefix: str) -> dict[str, str]:
    """Reads Google's subtotal, tax, and total for one group of amounts."""
    return {
        part: _money(
            source.get(f"{prefix}{part.title()}AmountMicros" if prefix else f"{part}AmountMicros")
        )
        for part in ("subtotal", "tax", "total")
    }


def _money(micros: Any) -> str:
    # Credits and adjustments are negative, so the sign is kept.
    try:
        return micros_to_money(int(micros or 0))
    except (TypeError, ValueError):
        return "0"


def _service_month(credit: Mapping[str, Any]) -> str | None:
    year = str(credit.get("originalYearOfService") or "")
    month = str(credit.get("originalMonthOfService") or "")
    if not year.isdigit() or month not in MONTHS:
        return None
    return _month_text(int(year), MONTHS.index(month))


def _month(value: str) -> tuple[int, int]:
    year, _, month = value.partition("-")
    return int(year), int(month)


def _month_text(year: int, month: int) -> str:
    return f"{year:04d}-{month + 1:02d}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _last_segment(resource_name: Any) -> str | None:
    text = str(resource_name or "").rsplit("/", 1)[-1].strip()
    return text[:64] or None


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] or None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] or None
