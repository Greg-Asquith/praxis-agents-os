# apps/api/integrations/meta_ads/operations/estimate_audience.py

"""Read Meta's estimated audience size for a targeting draft in one ad account."""

import json
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..throttle import ensure_account_available
from ..tools.schemas.targeting import MetaAdsAudienceEstimateData
from .targeting import MetaAdsTargeting, targeting_spec
from .values import invalid_response

_OPERATION = "estimate_audience"
_NO_ESTIMATE = "Meta has no estimate for this targeting yet. Try a broader audience."
_NOT_READY = "Meta's estimate isn't final yet, so the range may change."


async def estimate_audience(
    client: MetaAdsClient, *, account_id: str, targeting: MetaAdsTargeting
) -> MetaAdsAudienceEstimateData:
    ensure_account_available(account_id, operation=_OPERATION)
    payload = await client.graph_get(
        f"{ad_account_path(account_id)}/reachestimate",
        params={"targeting_spec": json.dumps(targeting_spec(targeting))},
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise invalid_response("Meta Ads returned an invalid estimate.", operation=_OPERATION)
    lower = _bound(data.get("users_lower_bound"))
    upper = _bound(data.get("users_upper_bound"))
    notes: list[str] = []
    if lower is None or upper is None:
        lower = upper = None
        notes.append(_NO_ESTIMATE)
    elif data.get("estimate_ready") is False:
        notes.append(_NOT_READY)
    return MetaAdsAudienceEstimateData(
        users_lower_bound=lower, users_upper_bound=upper, notes=notes
    )


def _bound(value: Any) -> int | None:
    # Meta reports -1 when it has no estimate.
    if value is None or value == -1:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise invalid_response("Meta Ads returned an invalid estimate.", operation=_OPERATION)
    return value
