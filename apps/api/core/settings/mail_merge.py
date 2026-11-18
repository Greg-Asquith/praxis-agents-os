# apps/api/core/settings/mail_merge.py

"""Mail merge caps and pacing."""

from pydantic import Field


class MailMergeSettingsMixin:
    """Daily caps sit at half of each provider's published limit for the account kind."""

    MAIL_MERGE_DAILY_CAP_GMAIL_PERSONAL: int = Field(
        default=250,
        ge=1,
        le=500,
        description="Merge and test sends a day from a gmail.com mailbox.",
    )
    MAIL_MERGE_DAILY_CAP_GOOGLE_WORKSPACE: int = Field(
        default=1000,
        ge=1,
        le=2000,
        description="Merge and test sends a day from a Google Workspace mailbox.",
    )
    MAIL_MERGE_DAILY_CAP_OUTLOOK_PERSONAL: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Merge and test sends a day from an Outlook.com mailbox.",
    )
    MAIL_MERGE_DAILY_CAP_MICROSOFT_365: int = Field(
        default=5000,
        ge=1,
        le=10000,
        description="Merge and test sends a day from a Microsoft 365 mailbox.",
    )
    # Microsoft 365 accepts 30 messages a minute, so two seconds is the floor.
    MAIL_MERGE_SEND_INTERVAL_SECONDS: int = Field(
        default=3, ge=2, le=60, description="Pause between two sends of one merge."
    )
    MAIL_MERGE_MAX_RECIPIENTS: int = Field(
        default=500, ge=1, le=500, description="Most recipients one merge can have."
    )
