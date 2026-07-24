# apps/api/services/integrations/events/domain.py

"""Inbound integration event vocabulary and internal verification signal."""

PROCESS_EVENT_KIND = "integrations.process_event"
REFRESH_WEBHOOKS_KIND = "integrations.refresh_webhooks"

EVENT_STATUS_RECEIVED = "received"
EVENT_STATUS_PROCESSED = "processed"
EVENT_STATUS_DISCARDED = "discarded"
TERMINAL_EVENT_STATUSES = frozenset({EVENT_STATUS_PROCESSED, EVENT_STATUS_DISCARDED})


class WebhookVerificationError(Exception):
    """Internal fail-closed signal carrying only an allowlisted reason code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code[:64]
        super().__init__("Integration webhook verification failed")
