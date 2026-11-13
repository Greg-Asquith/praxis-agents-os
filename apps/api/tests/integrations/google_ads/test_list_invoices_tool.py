# apps/api/tests/integrations/google_ads/test_list_invoices_tool.py

"""Invoices: what goes to Google, what is kept once, and where the bearer token may go."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.google_ads.client import GoogleAdsClient, GoogleAdsRequestRejectedError
from integrations.google_ads.tools import list_invoices as tool_module
from integrations.google_ads.tools.schemas.invoices import GoogleAdsInvoicesOutput
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _static_token, _writable_google_ads_entry

_PDF_URL = "https://ads.google.com/payments/doc/invoice-5391"
_PDF = b"%PDF-1.7 invoice"


def _entry(external_id: str = "111", *, manager: bool = False):
    return replace(
        _writable_google_ads_entry(),
        external_id=external_id,
        permissions_metadata={"login_customer_id": "999", "manager": manager},
    )


def _invoice(invoice_id: str, issue_date: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": invoice_id,
        "type": "INVOICE",
        "billingSetup": "customers/111/billingSetups/71",
        "issueDate": issue_date,
        "dueDate": "2026-11-30",
        "serviceDateRange": {"startDate": "2026-09-01", "endDate": "2026-09-30"},
        "currencyCode": "GBP",
        "subtotalAmountMicros": "3593800000",
        "taxAmountMicros": "719000000",
        "totalAmountMicros": "4312800000",
        "adjustmentsTotalAmountMicros": "-12500000",
        "pdfUrl": _PDF_URL,
        "accountBudgetSummaries": [
            {
                "customer": "customers/111",
                "customerDescriptiveName": "Northwind Outdoor UK",
                "accountBudget": "customers/111/accountBudgets/9",
                "accountBudgetName": "2026 retainer",
                "purchaseOrderNumber": "PO-4471",
                "servedAmountMicros": "3600000000",
                "billedAmountMicros": "3593800000",
                "invalidActivityAmountMicros": "-6200000",
                "invalidActivitySummaries": [
                    {
                        "amountMicros": "-6200000",
                        "originalInvoiceId": "5391-0039",
                        "originalMonthOfService": "AUGUST",
                        "originalYearOfService": "2026",
                    }
                ],
            },
            {"customer": "customers/222", "customerDescriptiveName": "Northwind Ireland"},
        ],
        **fields,
    }


class _InvoicesClient:
    """Answers the billing setup read, one invoice list per month, and PDF downloads."""

    def __init__(self, by_month: dict[str, list[dict[str, Any]]], *, pdf: bytes = _PDF) -> None:
        self.by_month = by_month
        self.pdf = pdf
        self.requests: list[dict[str, str]] = []
        self.downloads: list[str] = []
        self.refusal: Exception | None = None

    async def post(self, _path: str, **kwargs: Any) -> Any:
        assert "FROM billing_setup" in kwargs["json"]["query"]
        return [
            {
                "results": [
                    {
                        "billingSetup": {
                            "id": "71",
                            "status": "APPROVED",
                            "paymentsAccountInfo": {"paymentsAccountName": "UK Card"},
                        }
                    },
                    {"billingSetup": {"id": "72", "status": "PENDING"}},
                ]
            }
        ]

    async def get(self, path: str, **kwargs: Any) -> Any:
        assert path == "customers/111/invoices" and kwargs["login_customer_id"] == "999"
        self.requests.append(kwargs["params"])
        if self.refusal is not None:
            raise self.refusal
        return {"invoices": self.by_month.get(kwargs["params"]["issueMonth"], [])}

    async def download(self, url: str, **_kwargs: Any) -> bytes:
        self.downloads.append(url)
        return self.pdf


@asynccontextmanager
async def _transaction():
    yield


def _ctx(*entries):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
            db=SimpleNamespace(begin_nested=_transaction),
        ),
        tool_name="google_ads_list_invoices",
        tool_call_id="invoices-call",
    )


@pytest.fixture
def use(monkeypatch):
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    def install(client: _InvoicesClient) -> AsyncMock:
        monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=client))
        saved = AsyncMock(
            side_effect=lambda _deps, **kwargs: SimpleNamespace(
                file=SimpleNamespace(id=uuid4(), name=kwargs["name"]),
                bytes_written=len(kwargs["content"]),
            )
        )
        monkeypatch.setattr(tool_module, "create_copy", saved)
        return saved

    return install


async def _list(ctx, **kwargs):
    result = await tool_module.google_ads_list_invoices(
        ctx, **{"start_month": "2026-10", "end_month": "2026-11", **kwargs}
    )
    return result, GoogleAdsInvoicesOutput.model_validate(result).results


async def test_a_consolidated_invoice_in_two_months_is_kept_once_with_exact_amounts(use) -> None:
    shared = _invoice("5391-0042", "2026-10-03")
    client = _InvoicesClient(
        {"OCTOBER": [shared], "NOVEMBER": [shared, _invoice("5391-0050", "2026-11-02")]}
    )
    use(client)

    _raw, results = await _list(_ctx(_entry()))

    assert client.requests == [
        {
            "billingSetup": "customers/111/billingSetups/71",
            "issueYear": "2026",
            "issueMonth": month,
        }
        for month in ("OCTOBER", "NOVEMBER")
    ]
    data = results[0].data
    assert data.state == "listed"
    assert [setup.billing_setup_id for setup in data.billing_setups] == ["71"]
    assert [invoice.invoice_id for invoice in data.invoices] == ["5391-0050", "5391-0042"]
    invoice = data.invoices[1]
    assert (invoice.subtotal, invoice.tax, invoice.total) == ("3593.8", "719", "4312.8")
    assert invoice.adjustments.total == "-12.5"
    assert [line.customer_id for line in invoice.budget_lines] == ["111", "222"]
    line = invoice.budget_lines[0]
    assert (line.purchase_order_number, line.billed) == ("PO-4471", "3593.8")
    assert line.invalid_activity_credits[0].model_dump() == {
        "amount": "-6.2",
        "original_invoice_id": "5391-0039",
        "original_month": "2026-08",
        "original_account_budget_name": None,
        "original_purchase_order_number": None,
    }
    assert client.downloads == []


async def test_save_pdf_saves_each_invoice_once_and_keeps_googles_address_from_the_model(
    use,
) -> None:
    client = _InvoicesClient(
        {"OCTOBER": [_invoice("5391-0042", "2026-10-03"), _invoice("5391-0043", "2026-10-03")]}
    )
    saved = use(client)
    ctx = _ctx(_entry(), _entry(), _entry("900", manager=True))

    raw, results = await _list(ctx, invoice_ids=["5391-0042"], save_pdf=True, folder="Invoices")

    # Both selected entries list the one invoice asked for; the manager asks Google nothing.
    assert client.downloads == [_PDF_URL]
    saved.assert_awaited_once()
    assert saved.await_args.kwargs == {
        "name": "Google Ads Invoice 5391-0042.pdf",
        "content": _PDF,
        "content_type": "application/pdf",
        "folder": "Invoices",
    }
    first, second, manager = (entry.data for entry in results)
    assert [invoice.invoice_id for invoice in first.invoices] == ["5391-0042"]
    assert first.invoices[0].pdf.file.entity_id == second.invoices[0].pdf.file.entity_id
    assert first.invoices[0].pdf.size_bytes == len(_PDF)
    assert manager.state == "manager_account" and manager.invoices == []
    assert _PDF_URL not in str(raw)


async def test_a_reply_that_is_not_a_pdf_is_not_saved(use) -> None:
    client = _InvoicesClient(
        {"OCTOBER": [_invoice("5391-0042", "2026-10-03")]}, pdf=b"<html>Sign in</html>"
    )
    saved = use(client)

    _raw, results = await _list(_ctx(_entry()), save_pdf=True)

    saved.assert_not_awaited()
    invoice = results[0].data.invoices[0]
    assert invoice.pdf is None and "isn't a PDF" in invoice.pdf_error


async def test_pdfs_past_the_limit_for_one_call_are_left_for_the_next(use, monkeypatch) -> None:
    monkeypatch.setattr(tool_module, "_MAX_SAVED_PDFS", 1)
    client = _InvoicesClient(
        {"OCTOBER": [_invoice("5391-0042", "2026-10-03"), _invoice("5391-0043", "2026-10-02")]}
    )
    use(client)

    _raw, results = await _list(_ctx(_entry()), save_pdf=True)

    first, second = results[0].data.invoices
    assert first.pdf is not None and len(client.downloads) == 1
    assert second.pdf is None and "invoice_ids" in second.pdf_error


async def test_an_account_google_does_not_invoice_is_a_state_not_an_error(use) -> None:
    client = _InvoicesClient({})
    client.refusal = GoogleAdsRequestRejectedError(
        "Google Ads rejected the request.",
        failure={
            "details": [{"errors": [{"errorCode": {"invoiceError": "NOT_INVOICED_CUSTOMER"}}]}]
        },
        operation="list_invoices",
    )
    use(client)

    _raw, results = await _list(_ctx(_entry()))

    assert results[0].status == "success"
    assert results[0].data.state == "not_monthly_invoicing"
    assert results[0].data.billing_setups == []
    # The setup gets no invoices, so the remaining months aren't asked for.
    assert len(client.requests) == 1


async def test_more_than_twelve_months_is_refused_before_any_request(use) -> None:
    client = _InvoicesClient({})
    use(client)

    with pytest.raises(ModelRetry, match="12 months"):
        await _list(_ctx(_entry()), start_month="2025-10", end_month="2026-10")

    assert client.requests == []


async def test_download_sends_the_bearer_token_to_google_hosts_only() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(302, headers={"Location": "https://files.example.com/invoice.pdf"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = GoogleAdsClient(_static_token, client=http_client)
        for url in ("https://google.com.example.com/invoice.pdf", _PDF_URL):
            with pytest.raises(IntegrationValidationError) as error:
                await client.download(url, operation="list_invoices", max_bytes=1_000)
            assert error.value.error_code == "invalid_download_address"

    # Only Google's own address was asked, and its redirect off Google wasn't followed.
    assert [request.url.host for request in seen] == ["ads.google.com"]
    assert seen[0].headers["Authorization"] == "Bearer access-token"
