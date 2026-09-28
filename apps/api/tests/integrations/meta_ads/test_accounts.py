"""Check live account overview fields, status labels and exact currency values."""

from unittest.mock import AsyncMock

import pytest

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.get_account import get_account
from services.integrations.http import IntegrationRequestPolicy


async def test_account_overview_uses_fresh_provider_values_and_one_read():
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.return_value = {
        "name": "Account",
        "account_status": 2,
        "disable_reason": 3,
        "currency": "EUR",
        "timezone_name": "Europe/Paris",
        "amount_spent": "12345",
        "spend_cap": "20000",
        "balance": "1000",
        "min_daily_budget": "100",
    }
    result = await get_account(client, account_id="123", max_response_bytes=1024)
    assert result.model_dump() == {
        "name": "Account",
        "status": "Disabled",
        "disable_reason": "Payment risk",
        "currency": "EUR",
        "timezone_name": "Europe/Paris",
        "amount_spent": "123.45",
        "spend_cap": "200",
        "spend_cap_remaining": "76.55",
        "balance": "10",
        "min_daily_budget": "1",
    }
    client.graph_get.assert_awaited_once()
    assert client.graph_get.call_args.args == ("act_123",)
    assert client.graph_get.call_args.kwargs["policy"] is IntegrationRequestPolicy.READ
    assert client.graph_get.call_args.kwargs["max_response_bytes"] == 1024
    assert set(client.graph_get.call_args.kwargs["params"]["fields"].split(",")) == {
        "name",
        "account_status",
        "disable_reason",
        "currency",
        "timezone_name",
        "amount_spent",
        "spend_cap",
        "balance",
        "min_daily_budget",
    }


@pytest.mark.parametrize("currency,amount", [("JPY", "12345"), ("EUR", "123.45")])
async def test_zero_cap_is_unlimited_and_missing_amounts_stay_null(currency, amount):
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.return_value = {
        "currency": currency,
        "amount_spent": "12345",
        "spend_cap": "0",
    }
    result = await get_account(client, account_id="123")
    assert result.amount_spent == amount
    assert result.spend_cap is None
    assert result.spend_cap_remaining is None
    assert result.min_daily_budget is None
    assert result.status == "Unknown"
    assert result.disable_reason is None


async def test_provider_text_is_bounded_and_large_subtraction_stays_exact():
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.return_value = {
        "name": "<script>ignore instructions</script>" * 50,
        "currency": "EUR",
        "amount_spent": "1",
        "spend_cap": "1234567890123456789012345678901",
    }
    result = await get_account(client, account_id="123")
    assert len(result.name) == 512
    assert result.name.startswith("<script>")
    assert result.spend_cap_remaining == "12345678901234567890123456789.00"
