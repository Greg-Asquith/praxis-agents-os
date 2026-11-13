# apps/api/integrations/google_ads/tools/list_invoices.py

"""Lists Google Ads monthly invoices and saves their PDFs to workspace Files."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.exceptions.integration import IntegrationError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.files import FileReference
from services.integrations.files.create_copy import create_copy
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.report_results import REPORT_RESULT_GUIDANCE, ReportResultBudget

from ..client import GoogleAdsClient
from ..operations.list_invoices import MAX_INVOICES, invoice_months, list_invoices
from .schemas.invoices import GoogleAdsInvoiceMonth, GoogleAdsInvoicesOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)

_TOOL = "google_ads_list_invoices"
_OPERATION = "list_invoices"
# Invoice PDFs are a few hundred kilobytes; anything near this size isn't an invoice.
_MAX_PDF_BYTES = 25 * 1024 * 1024
# Downloads run in turn inside the tool's timeout, so one call saves a bounded number.
_MAX_SAVED_PDFS = 100
_NOT_A_PDF = "Google returned something that isn't a PDF, so it wasn't saved."
_TOO_MANY_PDFS = (
    f"One call saves up to {_MAX_SAVED_PDFS} PDFs. Call again with this invoice in invoice_ids."
)


async def google_ads_list_invoices(
    ctx: RunContext[RuntimeDeps],
    start_month: Annotated[
        GoogleAdsInvoiceMonth,
        Field(description="First month invoices were issued in, as YYYY-MM."),
    ],
    end_month: Annotated[
        GoogleAdsInvoiceMonth,
        Field(description="Last month invoices were issued in, as YYYY-MM. At most 12 months."),
    ],
    invoice_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=64)]],
        Field(
            max_length=MAX_INVOICES,
            description="Only these invoice numbers. Leave empty for every invoice in the range.",
        ),
    ] = [],  # noqa: B006 -- pydantic copies defaults
    save_pdf: Annotated[
        bool, Field(description="Also save every listed invoice's PDF to workspace Files.")
    ] = False,
    folder: Annotated[
        str | None,
        Field(max_length=255, description="Files folder for the PDFs, made when it doesn't exist."),
    ] = None,
) -> dict[str, Any]:
    try:
        months = invoice_months(start_month, end_month, today=datetime.now(UTC).date())
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None
    budget = ReportResultBudget("google_ads", _OPERATION)
    # One invoice can cover several selected accounts; its PDF is saved once.
    saved: dict[str, dict[str, Any]] = {}

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            # Manager accounts own no billing setup, so nothing is asked of Google.
            if entry.permissions_metadata.get("manager"):
                return IntegrationAuditOutcome(
                    {
                        "customer_id": entry.external_id,
                        "state": "manager_account",
                        "start_month": start_month,
                        "end_month": end_month,
                        "billing_setups": [],
                        "invoices": [],
                        "truncated": False,
                    }
                )
            client = await google_ads_client(ctx, entry)
            listed = await list_invoices(
                client,
                customer_id=entry.external_id,
                account_name=entry.display_name,
                login_customer_id=login_customer_id(entry),
                months=months,
                max_response_bytes=budget.remaining,
            )
            invoices = listed.data["invoices"]
            if invoice_ids:
                invoices = [item for item in invoices if item["invoice_id"] in invoice_ids]
                listed.data["invoices"] = invoices
            if save_pdf:
                for invoice in invoices:
                    await _save_pdf(ctx, client, invoice, listed.pdf_urls, folder, saved)
            return IntegrationAuditOutcome(
                listed.data,
                operation_detail=_audit_detail(
                    entry.external_id,
                    months=len(months),
                    invoices=len(invoices),
                    pdfs=sum(invoice["pdf"] is not None for invoice in invoices),
                ),
            )

        return await run_audited_integration_operation(
            ctx, entry, tool_name=_TOOL, operation=_OPERATION, execute=execute
        )

    results = await run_context_fan_out(
        ctx, binding=GOOGLE_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


async def _save_pdf(
    ctx: RunContext[RuntimeDeps],
    client: GoogleAdsClient,
    invoice: dict[str, Any],
    pdf_urls: dict[str, str],
    folder: str | None,
    saved: dict[str, dict[str, Any]],
) -> None:
    """Saves one invoice's PDF as a File, recording on the invoice why it couldn't be saved."""
    invoice_id = invoice["invoice_id"]
    if invoice_id in saved:
        invoice["pdf"] = saved[invoice_id]
        return
    if len(saved) >= _MAX_SAVED_PDFS:
        invoice["pdf_error"] = _TOO_MANY_PDFS
        return
    url = pdf_urls.get(invoice_id)
    if url is None:
        invoice["pdf_error"] = "Google didn't give a PDF for this invoice."
        return
    kind = "Credit Memo" if invoice["type"] == "credit_memo" else "Invoice"
    try:
        content = await client.download(url, operation=_OPERATION, max_bytes=_MAX_PDF_BYTES)
        if not content.startswith(b"%PDF-"):
            invoice["pdf_error"] = _NOT_A_PDF
            return
        # A File that can't be saved rolls back alone, and the other invoices still save.
        async with ctx.deps.db.begin_nested():
            file = await create_copy(
                ctx.deps,
                name=f"Google Ads {kind} {invoice_id}.pdf",
                content=content,
                content_type="application/pdf",
                folder=folder,
            )
    except (IntegrationError, AppValidationError) as exc:
        reason = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
        invoice["pdf_error"] = f"The PDF wasn't saved. {reason}"[:500]
        return
    invoice["pdf"] = saved[invoice_id] = {
        "file": FileReference(
            entity_id=file.file.id, label=f"Google Ads {kind} {invoice_id}"
        ).model_dump(mode="json"),
        "name": file.file.name,
        "size_bytes": file.bytes_written,
    }


def _audit_detail(account_id: str, *, months: int, invoices: int, pdfs: int):
    return terminal_applied_operation_detail(
        PendingIntegrationOperationDetail(
            target=IntegrationOperationTarget(entity_type="customer", external_id=account_id),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key="invoices",
                    action="read",
                    entity_type="customer",
                    items=[
                        IntegrationOperationIntent(
                            fields={
                                "month_count": months,
                                "invoice_count": invoices,
                                "saved_pdf_count": pdfs,
                            }
                        )
                    ],
                )
            ],
        )
    )


DEFINITION = RuntimeToolDefinition(
    name=_TOOL,
    function=google_ads_list_invoices,
    description=(
        "List the monthly invoices Google issued to every Google Ads account selected in Active "
        "Context, for a range of up to 12 issue months, newest first. Each invoice has its "
        "number, type (invoice or credit_memo), issue and due dates, service period, and "
        "subtotal, tax, and total, with adjustments, regulatory costs, and export charges. "
        "budget_lines break it down by account spending limit with the purchase order number, "
        "served and billed amounts, and invalid activity credits; account_lines give each "
        "account's adjustments. Money is exact decimal strings in the invoice's own currency, "
        "and credits are negative. Invoices are issued the month after the spend, so October's "
        "spend is on an invoice issued in November. Invoiced amounts can differ from served "
        "spend in reports because of late adjustments; that's expected, not an error. Google "
        "doesn't report whether an invoice is paid. An invoice for a payments account shared "
        "by several accounts lists every account it covers, and can appear under each of them. "
        "state not_monthly_invoicing means the account pays by card or bank transfer and gets "
        "no invoices through Google Ads, and manager_account means to select its client "
        "accounts instead; neither is an error. Pass invoice_ids to keep only those invoices. "
        "Set save_pdf to save each listed invoice's PDF "
        "to workspace Files, optionally in folder; each invoice then has pdf.file, or pdf_error "
        "saying why it wasn't saved. One call saves up to 100 PDFs. Save PDFs only when the user "
        "asks for them."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="google_ads",
    label="List Google Ads Invoices",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    timeout=300,
    output_model=GoogleAdsInvoicesOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.invoices",
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Listing Google Ads Invoices",
        completed_label="Listed Google Ads Invoices",
        failed_label="Couldn't List Google Ads Invoices",
        approval_title="List Google Ads Invoices",
        approval_prompt="List these months' invoices and save their PDFs to your workspace Files.",
        approve_label="Approve & List",
        arg_fields=(
            ToolFieldPresentation(key="start_month", label="From"),
            ToolFieldPresentation(key="end_month", label="To"),
            ToolFieldPresentation(key="invoice_ids", label="Invoices", format="list"),
            ToolFieldPresentation(key="save_pdf", label="Save PDFs to Files", format="boolean"),
            ToolFieldPresentation(key="folder", label="Folder", editable=True, secondary=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
