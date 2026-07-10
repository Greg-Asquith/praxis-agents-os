# apps/api/services/integrations/credentials/__init__.py

"""Credential operations.

Webhook MAC secrets use the same reference service, with names shaped as
``integrations/{provider_key}/{connection_id}/webhook/{webhook_id}``.
"""

from services.integrations.credentials.ensure_fresh_credential import (
    ensure_fresh_credential,
)
from services.integrations.credentials.find_duplicate_principals import (
    find_duplicate_principals,
)
from services.integrations.credentials.revoke_credential import revoke_credential
from services.integrations.credentials.store_oauth_credential import store_oauth_credential
from services.integrations.credentials.store_secret_reference_credential import (
    store_secret_reference_credential,
)

__all__ = [
    "ensure_fresh_credential",
    "find_duplicate_principals",
    "revoke_credential",
    "store_oauth_credential",
    "store_secret_reference_credential",
]
