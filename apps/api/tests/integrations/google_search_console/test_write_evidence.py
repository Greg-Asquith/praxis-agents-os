# apps/api/tests/integrations/google_search_console/test_write_evidence.py

"""Search Console sitemap mutation evidence coverage."""

import pytest
from pydantic import ValidationError

from integrations.google_search_console.tools.schemas.sitemap_submission import (
    GoogleSearchConsoleSitemapSubmissionResult,
)


def test_sitemap_result_rejects_error_codes_outside_the_public_contract() -> None:
    with pytest.raises(ValidationError):
        GoogleSearchConsoleSitemapSubmissionResult.model_validate(
            {
                "sitemap_url": "https://example.com/sitemap.xml",
                "outcome": "failed",
                "previously_submitted": False,
                "status_read": False,
                "error_code": "IntegrationPermissionError",
            }
        )
