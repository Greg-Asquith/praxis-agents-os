# apps/api/integrations/google_ads/operations/account_billing.py

"""Reads who pays for a Google Ads account and the spending limit in force."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from core.exceptions.integration import IntegrationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, GoogleAdsRequestRejectedError
from ..references import GoogleAdsAccountBudgetReference, GoogleAdsBillingSetupReference
from ..tools.utils.money import micros_to_money
from .invoice_requests import list_invoice_month, refused_as_not_invoiced
from .utils import nonnegative_int, stream_rows

type BillingState = Literal[
    "not_monthly_invoicing",
    "setup_pending",
    "no_active_limit",
    "active",
    "running_low",
    "limit_reached",
]

_OPERATION = "get_account_billing"
# Accounts hold a handful of each; the newest are kept when there are more.
_MAX_ROWS = 200
# Google's billing date-times are "YYYY-MM-DD HH:MM:SS" in the account time zone.
_DATE_TIME_LENGTH = 19
# A limit is running low when less than this many days of this month's average cost is left.
_LOW_LIMIT_DAYS = 7
_PROPOSAL_KINDS = {"CREATE": "create", "UPDATE": "update", "END": "end", "REMOVE": "remove"}
_SETUP_QUERY = """
SELECT
  billing_setup.id,
  billing_setup.status,
  billing_setup.start_date_time,
  billing_setup.payments_account_info.payments_account_id,
  billing_setup.payments_account_info.payments_account_name,
  billing_setup.payments_account_info.payments_profile_id,
  billing_setup.payments_account_info.payments_profile_name
FROM billing_setup
ORDER BY billing_setup.id DESC
LIMIT 200
""".strip()
_BUDGET_QUERY = """
SELECT
  account_budget.id,
  account_budget.name,
  account_budget.status,
  account_budget.adjusted_spending_limit_micros,
  account_budget.adjusted_spending_limit_type,
  account_budget.approved_spending_limit_micros,
  account_budget.approved_spending_limit_type,
  account_budget.amount_served_micros,
  account_budget.approved_start_date_time,
  account_budget.proposed_start_date_time,
  account_budget.approved_end_date_time,
  account_budget.approved_end_time_type,
  account_budget.purchase_order_number,
  account_budget.pending_proposal.account_budget_proposal,
  account_budget.pending_proposal.proposal_type,
  account_budget.pending_proposal.spending_limit_micros,
  account_budget.pending_proposal.spending_limit_type,
  account_budget.pending_proposal.start_date_time,
  account_budget.pending_proposal.end_date_time,
  account_budget.pending_proposal.end_time_type,
  account_budget.pending_proposal.creation_date_time
FROM account_budget
ORDER BY account_budget.id DESC
LIMIT 200
""".strip()


async def read_billing_setups(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    max_response_bytes: int,
    operation: str = _OPERATION,
) -> list[Mapping[str, Any]]:
    """Returns the account's billing setups that aren't cancelled, newest first."""
    rows = await _search(
        client, customer_id, login_customer_id, _SETUP_QUERY, max_response_bytes, operation
    )
    return _newest_first(
        row["billingSetup"]
        for row in rows
        if isinstance(row.get("billingSetup"), Mapping)
        and row["billingSetup"].get("status") != "CANCELLED"
    )


def billing_setup_reference(
    setup: Mapping[str, Any], *, customer_id: str, account_name: str
) -> GoogleAdsBillingSetupReference:
    """Builds the setup's reference, labelled with the payments account that pays."""
    payments = setup.get("paymentsAccountInfo")
    name = _text(payments.get("paymentsAccountName")) if isinstance(payments, Mapping) else None
    return GoogleAdsBillingSetupReference(
        customer_id=customer_id,
        billing_setup_id=str(setup.get("id")),
        label=name or f"Billing setup {setup.get('id')}",
        scope_label=account_name,
    )


async def read_account_billing(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    account_name: str,
    login_customer_id: str,
    max_response_bytes: int,
    local_now: datetime,
    cost_this_month_micros: int,
) -> dict[str, Any]:
    """Returns the payer, the spending limits, and any change waiting for Google's review.

    `local_now` is in the account time zone. Only accounts on monthly invoicing have spending
    limits that mean anything; an account with no billing setup, with a setup and no limit of
    any status, or whose setup Google issues no invoices for, is reported as paid another way.
    """
    setups = await read_billing_setups(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        max_response_bytes=max_response_bytes,
    )
    if not setups:
        return _billing("not_monthly_invoicing", monthly_invoicing=False)
    now = local_now.strftime("%Y-%m-%d %H:%M:%S")
    approved_setups = [item for item in setups if item.get("status") == "APPROVED"]
    # A payer switch is approved before it starts, so the setup that has started pays now.
    setup = next(
        (item for item in approved_setups if (_date_time(item.get("startDateTime")) or "") <= now),
        (approved_setups or setups)[0],
    )
    all_budgets = _newest_first(
        row["accountBudget"]
        for row in await _search(
            client, customer_id, login_customer_id, _BUDGET_QUERY, max_response_bytes, _OPERATION
        )
        if isinstance(row.get("accountBudget"), Mapping)
    )
    if setup.get("status") == "APPROVED" and not (
        all_budgets
        and await _invoiced(
            client, customer_id, login_customer_id, setup, local_now, max_response_bytes
        )
    ):
        return _billing("not_monthly_invoicing", monthly_invoicing=False)
    # Pending budgets are new limits waiting for Google; cancelled ones never served.
    budgets = [item for item in all_budgets if item.get("status") in ("APPROVED", "PENDING")]

    def reference(budget: Mapping[str, Any]) -> dict[str, Any]:
        name = str(budget.get("name") or "").strip()
        return GoogleAdsAccountBudgetReference(
            customer_id=customer_id,
            account_budget_id=str(budget.get("id")),
            label=name[:500] or f"Spending limit {budget.get('id')}",
            scope_label=account_name,
        ).model_dump(mode="json")

    approved = [item for item in budgets if item.get("status") == "APPROVED"]
    active = next(
        (item for item in approved if _started(item, now) and not _ended(item, now)), None
    )
    state = _state(setup, active, cost_this_month_micros, local_now.day)
    payments = setup.get("paymentsAccountInfo")
    payments = payments if isinstance(payments, Mapping) else {}
    return {
        **_billing(state, monthly_invoicing=True),
        "billing_setup": billing_setup_reference(
            setup, customer_id=customer_id, account_name=account_name
        ).model_dump(mode="json"),
        "billing_setup_status": str(setup.get("status") or "UNKNOWN"),
        "payments_account_id": _text(payments.get("paymentsAccountId")),
        "payments_account_name": _text(payments.get("paymentsAccountName")),
        "payments_profile_id": _text(payments.get("paymentsProfileId")),
        "payments_profile_name": _text(payments.get("paymentsProfileName")),
        "active_limit": _spending_limit(active, reference(active)) if active else None,
        "queued_limits": [
            _spending_limit(item, reference(item))
            for item in reversed(approved)
            if not _started(item, now)
        ],
        "last_ended_limit": next(
            (_spending_limit(item, reference(item)) for item in approved if _ended(item, now)),
            None,
        ),
        "pending_changes": [
            _pending_change(item, reference(item))
            for item in budgets
            if isinstance(item.get("pendingProposal"), Mapping)
            and item["pendingProposal"].get("accountBudgetProposal")
        ],
    }


async def _invoiced(
    client: GoogleAdsClient,
    customer_id: str,
    login_customer_id: str,
    setup: Mapping[str, Any],
    local_now: datetime,
    max_response_bytes: int,
) -> bool:
    """Checks whether Google issues invoices for the setup, by asking for this month's.

    Accounts paid by card or bank transfer can hold a spending limit with no ceiling, so a
    limit alone doesn't mean monthly invoicing. A request Google refuses for another reason
    leaves the answer unknown, and the limits are still reported.
    """
    try:
        await list_invoice_month(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            billing_setup=f"customers/{customer_id}/billingSetups/{setup.get('id')}",
            year=local_now.year,
            month=local_now.month - 1,
            max_response_bytes=max_response_bytes,
        )
    except GoogleAdsRequestRejectedError as exc:
        return not refused_as_not_invoiced(exc)
    except IntegrationError:
        return True
    return True


async def _search(
    client: GoogleAdsClient,
    customer_id: str,
    login_customer_id: str,
    query: str,
    max_response_bytes: int,
    operation: str,
) -> list[dict[str, Any]]:
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation=operation,
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
        max_response_bytes=max_response_bytes,
    )
    return stream_rows(payload, max_rows=_MAX_ROWS)


def _billing(state: BillingState, *, monthly_invoicing: bool) -> dict[str, Any]:
    return {
        "monthly_invoicing": monthly_invoicing,
        "state": state,
        "billing_setup": None,
        "billing_setup_status": None,
        "payments_account_id": None,
        "payments_account_name": None,
        "payments_profile_id": None,
        "payments_profile_name": None,
        "active_limit": None,
        "queued_limits": [],
        "last_ended_limit": None,
        "pending_changes": [],
    }


def _state(
    setup: Mapping[str, Any],
    active: Mapping[str, Any] | None,
    cost_this_month_micros: int,
    day_of_month: int,
) -> BillingState:
    if setup.get("status") != "APPROVED":
        return "setup_pending"
    if active is None:
        return "no_active_limit"
    left = _left_micros(active)
    if left is None:
        return "active"
    if left <= 0:
        return "limit_reached"
    # Compares in micros so a month's average never rounds a nearly spent limit up.
    if left * day_of_month < _LOW_LIMIT_DAYS * cost_this_month_micros:
        return "running_low"
    return "active"


def _spending_limit(budget: Mapping[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    limit = _limit_in_force(budget)
    left = _left_micros(budget)
    return {
        "account_budget": reference,
        "limit": _money(limit),
        "served": micros_to_money(_served_micros(budget)),
        "left": _money(left),
        "starts": _start(budget),
        "ends": _end(budget, "approvedEndDateTime", "approvedEndTimeType"),
        "purchase_order_number": _text(budget.get("purchaseOrderNumber")),
    }


def _pending_change(budget: Mapping[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    proposal = budget["pendingProposal"]
    limit = (
        None
        if proposal.get("spendingLimitType") == "INFINITE"
        else nonnegative_int(proposal.get("spendingLimitMicros"))
    )
    return {
        "account_budget": reference,
        "kind": _PROPOSAL_KINDS.get(str(proposal.get("proposalType")), "unknown"),
        "limit": _money(limit),
        "starts": _date_time(proposal.get("startDateTime")),
        "ends": _end(proposal, "endDateTime", "endTimeType"),
        "submitted": _date_time(proposal.get("creationDateTime")),
    }


def _limit_in_force(budget: Mapping[str, Any]) -> int | None:
    """Returns the limit Google enforces in micros, or None when there's no limit."""
    for key in ("adjustedSpendingLimit", "approvedSpendingLimit"):
        if budget.get(f"{key}Type") == "INFINITE":
            return None
        if (micros := nonnegative_int(budget.get(f"{key}Micros"))) is not None:
            return micros
    return None


def _served_micros(budget: Mapping[str, Any]) -> int:
    return nonnegative_int(budget.get("amountServedMicros")) or 0


def _left_micros(budget: Mapping[str, Any]) -> int | None:
    limit = _limit_in_force(budget)
    return limit - _served_micros(budget) if limit is not None else None


def _money(micros: int | None) -> str | None:
    return micros_to_money(micros) if micros is not None else None


def _start(budget: Mapping[str, Any]) -> str | None:
    # Google leaves the approved start empty for budgets made before 2019.
    return _date_time(budget.get("approvedStartDateTime")) or _date_time(
        budget.get("proposedStartDateTime")
    )


def _end(values: Mapping[str, Any], date_key: str, type_key: str) -> str | None:
    """Returns the end date-time, or None when the limit runs until it's ended."""
    if values.get(type_key) == "FOREVER":
        return None
    return _date_time(values.get(date_key))


def _started(budget: Mapping[str, Any], now: str) -> bool:
    start = _start(budget)
    return start is None or start <= now


def _ended(budget: Mapping[str, Any], now: str) -> bool:
    end = _end(budget, "approvedEndDateTime", "approvedEndTimeType")
    return end is not None and end <= now


def _newest_first(items: Any) -> list[Mapping[str, Any]]:
    return sorted(items, key=lambda item: nonnegative_int(item.get("id")) or 0, reverse=True)


def _date_time(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:_DATE_TIME_LENGTH] or None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] or None
