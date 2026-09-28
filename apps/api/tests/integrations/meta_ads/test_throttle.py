import json

import pytest

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationRateLimitError
from integrations.meta_ads import throttle


def _headers(*, utilisation: float = 100, minutes: float = 2) -> dict[str, str]:
    return {
        "X-FB-Ads-Insights-Throttle": json.dumps({"acc_id_util_pct": utilisation}),
        "X-Business-Use-Case-Usage": json.dumps(
            {"123": [{"type": "ads_insights", "estimated_time_to_regain_access": minutes}]}
        ),
    }


def test_throttle_is_per_account_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 10.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", _headers())
    throttle.ensure_account_available("456", operation="run_insights")
    with pytest.raises(IntegrationRateLimitError, match="2 minutes") as caught:
        throttle.ensure_account_available("123", operation="run_insights")
    assert caught.value.failure_disposition == IntegrationFailureDisposition.NOT_DISPATCHED
    assert caught.value.provider_key == "meta_ads"
    now = 71
    with pytest.raises(IntegrationRateLimitError, match="1 minute"):
        throttle.ensure_account_available("123", operation="run_insights")
    now = 130
    throttle.ensure_account_available("123", operation="run_insights")


def test_business_insights_usage_and_longest_wait_are_used() -> None:
    headers = {
        "X-Business-Use-Case-Usage": json.dumps(
            {
                "123": [
                    {
                        "type": "ads_insights",
                        "total_time": 100,
                        "estimated_time_to_regain_access": 3,
                    }
                ]
            }
        ),
        "X-Ad-Account-Usage": '{"acc_id_util_pct": 50, "reset_time_duration": 60}',
    }
    throttle.record_usage("123", headers)
    with pytest.raises(IntegrationRateLimitError, match="3 minutes"):
        throttle.ensure_account_available("123", operation="run_insights")


def test_below_limit_and_missing_wait_do_not_block() -> None:
    throttle.record_usage("123", _headers(utilisation=99))
    throttle.ensure_account_available("123", operation="run_insights")
    throttle.record_usage("456", {"X-FB-Ads-Insights-Throttle": '{"acc_id_util_pct": 100}'})
    throttle.ensure_account_available("456", operation="run_insights")


def test_valid_update_clears_throttle_and_missing_headers_preserve_it() -> None:
    throttle.record_usage("123", _headers())
    throttle.record_usage("123", {})
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("123", operation="run_insights")
    throttle.record_usage("123", _headers(utilisation=20, minutes=0))
    throttle.ensure_account_available("123", operation="run_insights")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "{invalid",
        "null",
    ],
)
def test_malformed_headers_are_ignored(raw: str) -> None:
    headers = dict.fromkeys(
        ("x-fb-ads-insights-throttle", "x-ad-account-usage", "x-business-use-case-usage"), raw
    )
    throttle.record_usage("123", headers)
    throttle.ensure_account_available("123", operation="run_insights")
    assert "few minutes" in throttle.throttle_message(headers)


def test_capacity_evicts_least_recently_used_account(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    monkeypatch.setattr(throttle, "_MAX_KEYS", 2)
    throttle.record_usage("first", _headers())
    now = 1
    throttle.record_usage("second", _headers())
    now = 2
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("first", operation="run_insights")
    now = 3
    throttle.record_usage("third", _headers())
    assert set(throttle._accounts) == {"first", "third"}


def test_app_insights_limit_also_blocks_the_observed_account():
    throttle.record_usage(
        "123",
        {
            "X-FB-Ads-Insights-Throttle": '{"app_id_util_pct":100,"acc_id_util_pct":5}',
            "X-Ad-Account-Usage": '{"reset_time_duration":120}',
        },
    )
    with pytest.raises(IntegrationRateLimitError, match="2 minutes"):
        throttle.ensure_account_available("123", operation="run_insights")


def test_healthy_account_header_cannot_shorten_an_active_insights_cooldown(monkeypatch):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", _headers(minutes=2))
    now = 1.0
    throttle.record_usage(
        "123",
        {
            "X-Ad-Account-Usage": '{"acc_id_util_pct":20,"reset_time_duration":0}',
        },
    )
    with pytest.raises(IntegrationRateLimitError, match="2 minutes"):
        throttle.ensure_account_available("123", operation="run_insights")
    now = 120.0
    throttle.ensure_account_available("123", operation="run_insights")


def _account_headers(utilisation=100, seconds=120):
    return {
        "X-Ad-Account-Usage": json.dumps(
            {"acc_id_util_pct": utilisation, "reset_time_duration": seconds}
        )
    }


@pytest.mark.parametrize(
    "initial,healthy",
    [
        (_headers(), _account_headers(20, 600)),
    ],
)
def test_expired_quota_is_not_revived_by_another_healthy_quota(monkeypatch, initial, healthy):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", initial)
    now = 121.0
    throttle.ensure_account_available("123", operation="run_insights")
    throttle.record_usage("123", healthy)
    throttle.ensure_account_available("123", operation="run_insights")


@pytest.mark.parametrize(
    "initial,other",
    [
        (_headers(minutes=2), _account_headers(seconds=300)),
    ],
)
def test_overlapping_quota_deadlines_remain_independent(monkeypatch, initial, other):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", initial)
    now = 10.0
    throttle.record_usage("123", other)
    now = 121.0
    with pytest.raises(IntegrationRateLimitError, match="4 minutes"):
        throttle.ensure_account_available("123", operation="run_insights")
    now = 310.0
    throttle.ensure_account_available("123", operation="run_insights")
