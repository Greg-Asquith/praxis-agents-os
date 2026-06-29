# apps/api/core/settings/azure.py

"""Azure infrastructure provider settings."""

from pydantic import Field, field_validator


class AzureSettingsMixin:
    # Azure Configuration
    AZURE_STORAGE_ACCOUNT_NAME: str = Field(
        default="",
        description="Azure Blob Storage account name. Required when CLOUD_PROVIDER=azure.",
    )
    AZURE_STORAGE_PUBLIC_CONTAINER: str = Field(
        default="",
        description="Azure Blob container for public assets. Required when CLOUD_PROVIDER=azure.",
    )
    AZURE_STORAGE_PRIVATE_CONTAINER: str = Field(
        default="",
        description="Azure Blob container for private originals and documents. Required when CLOUD_PROVIDER=azure.",
    )
    AZURE_STORAGE_ACCOUNT_URL: str | None = Field(
        default=None,
        description=(
            "Optional Azure Blob account URL override. If not set, runtime should derive "
            "https://<AZURE_STORAGE_ACCOUNT_NAME>.blob.core.windows.net."
        ),
    )
    AZURE_MANAGED_IDENTITY_CLIENT_ID: str = Field(
        default="",
        description=(
            "Optional user-assigned managed identity client ID for Azure credential resolution. "
            "Keep empty for system-assigned identity or local development."
        ),
    )
    AZURE_KEY_VAULT_URL: str | None = Field(
        default=None,
        description=(
            "Azure Key Vault URL used for runtime secret resolution when CLOUD_PROVIDER=azure "
            "(for example https://example-vault.vault.azure.net)."
        ),
    )

    @field_validator("AZURE_STORAGE_ACCOUNT_URL", mode="before")
    @classmethod
    def normalize_azure_storage_account_url(cls, v):
        """Normalize optional Azure storage account URL values."""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s == "" or s.lower() in ("none", "null", "false", "0"):
                return None
            if not s.startswith(("http://", "https://")):
                raise ValueError("AZURE_STORAGE_ACCOUNT_URL must start with http:// or https://")
            return s.rstrip("/")
        return None
