"""Tests for workspace document and chat attachment settings."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_document_attachment_settings_have_bounded_defaults() -> None:
    resolved = Settings(_env_file=None)

    assert resolved.MAX_FILE_SIZE_DOCUMENT == 100 * 1024 * 1024
    assert resolved.MAX_MULTIMODAL_DOCUMENT_BYTES == 20 * 1024 * 1024
    assert resolved.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS == 60


def test_document_size_accepts_250_mib_ceiling() -> None:
    resolved = Settings(_env_file=None, MAX_FILE_SIZE_DOCUMENT=250 * 1024 * 1024)

    assert resolved.MAX_FILE_SIZE_DOCUMENT == 250 * 1024 * 1024


def test_document_size_rejects_value_above_250_mib() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 262144000"):
        Settings(_env_file=None, MAX_FILE_SIZE_DOCUMENT=250 * 1024 * 1024 + 1)


@pytest.mark.parametrize("timeout", [4, 301])
def test_attachment_conversion_timeout_stays_between_5_and_300_seconds(
    timeout: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS=timeout)
