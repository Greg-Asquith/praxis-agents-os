# apps/api/integrations/google_ads/operations/invoice_requests.py

"""Asks Google for one billing setup's invoices in one month.

Google has no field that says how an account pays. Its answer to this request is the only
read that tells an account on monthly invoicing from one paid by card or bank transfer.
"""

from typing import Any

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationPermissionError,
)
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, GoogleAdsRequestRejectedError, provider_errors

INVOICES_OPERATION = "list_invoices"
MONTHS = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)
# Google's refusals for a setup that gets no invoices, which is a state and not a failure.
_NOT_INVOICED = frozenset(
    {
        "NOT_INVOICED_CUSTOMER",
        "NON_SERVING_CUSTOMER",
        "BILLING_SETUP_NOT_ON_MONTHLY_INVOICING",
        "BILLING_SETUP_NOT_APPROVED",
    }
)
_NOT_PERMITTED = (
    "Google didn't let this sign-in read the invoices. Google shows invoices only through the "
    "manager account that pays for this account, to someone with billing access."
)


async def list_invoice_month(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    billing_setup: str,
    year: int,
    month: int,
    max_response_bytes: int,
) -> Any:
    """Lists the invoices one billing setup was issued in one month, `month` counted from 0.

    Raises:
        IntegrationPermissionError: When this sign-in can't read the account's invoices.
        GoogleAdsRequestRejectedError: For Google's other refusals; `refused_as_not_invoiced`
            tells whether one means the setup gets no invoices.
    """
    try:
        return await client.get(
            f"customers/{customer_id}/invoices",
            operation=INVOICES_OPERATION,
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            params={
                "billingSetup": billing_setup,
                "issueYear": str(year),
                "issueMonth": MONTHS[month],
            },
            max_response_bytes=max_response_bytes,
        )
    except IntegrationPermissionError as exc:
        # A refusal with its own fix, such as an unapproved Cloud project, keeps it.
        if exc.error_code:
            raise
        raise _not_permitted() from None
    except GoogleAdsRequestRejectedError as exc:
        if "ACTION_NOT_PERMITTED" in _error_codes(exc.failure):
            raise _not_permitted() from None
        raise


def refused_as_not_invoiced(refusal: GoogleAdsRequestRejectedError) -> bool:
    """Checks whether Google refused because the billing setup gets no invoices."""
    return bool(_NOT_INVOICED.intersection(_error_codes(refusal.failure)))


def _not_permitted() -> IntegrationPermissionError:
    return IntegrationPermissionError(
        _NOT_PERMITTED,
        provider_key="google_ads",
        operation=INVOICES_OPERATION,
        error_code="invoices_not_permitted",
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )


def _error_codes(failure: dict[str, Any]) -> set[str]:
    return {
        str(code)
        for error in provider_errors(failure)
        if isinstance(error.get("errorCode"), dict)
        for code in error["errorCode"].values()
    }
