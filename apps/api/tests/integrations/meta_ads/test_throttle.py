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
    throttle.ensure_account_available("456")
    with pytest.raises(IntegrationRateLimitError, match="2 minutes") as caught:
        throttle.ensure_account_available("123")
    assert caught.value.failure_disposition == IntegrationFailureDisposition.NOT_DISPATCHED
    assert caught.value.provider_key == "meta_ads"
    now = 71
    with pytest.raises(IntegrationRateLimitError, match="1 minute"):
        throttle.ensure_account_available("123")
    now = 130
    throttle.ensure_account_available("123")


def test_account_usage_reset_is_in_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    headers = {"x-ad-account-usage": '{"acc_id_util_pct": 100, "reset_time_duration": 90}'}
    throttle.record_usage("123", headers)
    assert "2 minutes" in throttle.throttle_message(headers)
    now = 89
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("123")
    now = 90
    throttle.ensure_account_available("123")


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
        throttle.ensure_account_available("123")


def test_below_limit_and_missing_wait_do_not_block() -> None:
    throttle.record_usage("123", _headers(utilisation=99))
    throttle.ensure_account_available("123")
    throttle.record_usage("456", {"X-FB-Ads-Insights-Throttle": '{"acc_id_util_pct": 100}'})
    throttle.ensure_account_available("456")


def test_valid_update_clears_throttle_and_missing_headers_preserve_it() -> None:
    throttle.record_usage("123", _headers())
    throttle.record_usage("123", {})
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("123")
    throttle.record_usage("123", _headers(utilisation=20, minutes=0))
    throttle.ensure_account_available("123")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "{invalid",
        "null",
        "[]",
        '"text"',
        '{"acc_id_util_pct": true, "reset_time_duration": true}',
        '{"acc_id_util_pct": "100", "reset_time_duration": "90"}',
        '{"acc_id_util_pct": NaN, "reset_time_duration": Infinity}',
        '{"acc_id_util_pct": -100, "reset_time_duration": -90}',
        '{"acc_id_util_pct": 1e100, "reset_time_duration": 1e100}',
        "[" * 2000 + "]" * 2000,
        " " * 16385,
    ],
)
def test_malformed_headers_are_ignored(raw: str) -> None:
    headers = dict.fromkeys(
        ("x-fb-ads-insights-throttle", "x-ad-account-usage", "x-business-use-case-usage"), raw
    )
    throttle.record_usage("123", headers)
    throttle.ensure_account_available("123")
    assert "few minutes" in throttle.throttle_message(headers)


def test_business_entries_are_defensive_and_wait_is_bounded() -> None:
    headers = {
        "X-Business-Use-Case-Usage": '{"123": [null, "bad", {"estimated_time_to_regain_access": 86400}], "456": null}'
    }
    assert "1440 minutes" in throttle.throttle_message(headers)


def test_idle_eviction_retains_known_throttle_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("idle", _headers(utilisation=20, minutes=0))
    throttle.record_usage("blocked", _headers(minutes=10))
    now = 301
    throttle.ensure_account_available("idle")
    assert "idle" not in throttle._accounts
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("blocked")
    now = 602
    throttle.ensure_account_available("blocked")
    assert "blocked" not in throttle._accounts


def test_capacity_evicts_least_recently_used_account(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    monkeypatch.setattr(throttle, "_MAX_KEYS", 2)
    throttle.record_usage("first", _headers())
    now = 1
    throttle.record_usage("second", _headers())
    now = 2
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("first")
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
        throttle.ensure_account_available("123")


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
        throttle.ensure_account_available("123")
    now = 120.0
    throttle.ensure_account_available("123")


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
        (_account_headers(), _headers(utilisation=20, minutes=10)),
    ],
)
def test_expired_quota_is_not_revived_by_another_healthy_quota(monkeypatch, initial, healthy):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", initial)
    now = 121.0
    throttle.ensure_account_available("123")
    throttle.record_usage("123", healthy)
    throttle.ensure_account_available("123")


@pytest.mark.parametrize(
    "initial,other",
    [
        (_headers(minutes=2), _account_headers(seconds=300)),
        (_account_headers(seconds=120), _headers(minutes=5)),
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
        throttle.ensure_account_available("123")
    now = 310.0
    throttle.ensure_account_available("123")


@pytest.mark.parametrize(
    "initial,healthy",
    [
        (_headers(), _account_headers(20, 600)),
        (_account_headers(), _headers(utilisation=20, minutes=10)),
    ],
)
def test_healthy_partial_update_cannot_extend_independent_cooldown(monkeypatch, initial, healthy):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", initial)
    now = 10.0
    throttle.record_usage("123", healthy)
    with pytest.raises(IntegrationRateLimitError, match="2 minutes"):
        throttle.ensure_account_available("123")
    now = 120.0
    throttle.ensure_account_available("123")


def test_shorter_saturated_update_does_not_shorten_same_quota(monkeypatch):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage("123", _headers(minutes=5))
    now = 10.0
    throttle.record_usage("123", _headers(minutes=1))
    now = 299.0
    with pytest.raises(IntegrationRateLimitError):
        throttle.ensure_account_available("123")
    now = 300.0
    throttle.ensure_account_available("123")


def test_healthy_account_wait_does_not_qualify_saturated_insights():
    throttle.record_usage(
        "123",
        {
            "X-FB-Ads-Insights-Throttle": '{"app_id_util_pct":100}',
            **_account_headers(20, 600),
        },
    )
    throttle.ensure_account_available("123")


def test_healthy_insights_account_does_not_clear_app_limit(monkeypatch):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage(
        "123",
        {
            "X-FB-Ads-Insights-Throttle": '{"app_id_util_pct":100}',
            "X-Ad-Account-Usage": '{"reset_time_duration":120}',
        },
    )
    throttle.record_usage("123", _headers(utilisation=20, minutes=10))
    with pytest.raises(IntegrationRateLimitError, match="2 minutes"):
        throttle.ensure_account_available("123")
    now = 120.0
    throttle.ensure_account_available("123")


@pytest.mark.parametrize(
    "entry",
    [
        {"type": "ads_insights", "call_count": 20, "estimated_time_to_regain_access": 10},
        {"type": "other", "estimated_time_to_regain_access": 10},
    ],
)
def test_unrelated_business_wait_does_not_qualify_saturated_insights(entry):
    throttle.record_usage(
        "123",
        {
            "X-FB-Ads-Insights-Throttle": '{"app_id_util_pct":100}',
            "X-Business-Use-Case-Usage": json.dumps({"123": [entry]}),
        },
    )
    throttle.ensure_account_available("123")


def test_healthy_business_entry_does_not_extend_saturated_entry(monkeypatch):
    now = 0.0
    monkeypatch.setattr(throttle, "monotonic", lambda: now)
    throttle.record_usage(
        "123",
        {
            "X-Business-Use-Case-Usage": json.dumps(
                {
                    "123": [
                        {
                            "type": "ads_insights",
                            "call_count": 100,
                            "estimated_time_to_regain_access": 2,
                        },
                        {
                            "type": "ads_insights",
                            "call_count": 20,
                            "estimated_time_to_regain_access": 10,
                        },
                    ]
                }
            ),
        },
    )
    with pytest.raises(IntegrationRateLimitError, match="2 minutes"):
        throttle.ensure_account_available("123")
    now = 120.0
    throttle.ensure_account_available("123")
