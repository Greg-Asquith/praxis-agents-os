"""Cloud secret providers honor the common versioned-reference contract."""

from types import SimpleNamespace

import pytest

from services.secrets.domain import SecretReference
from services.secrets.providers.aws_secrets_manager import AwsSecretsManagerProvider
from services.secrets.providers.azure_key_vault import AzureKeyVaultProvider
from services.secrets.providers.gcp_secret_manager import GcpSecretManagerProvider
from services.secrets.utils import cloud_secret_id

pytestmark = pytest.mark.asyncio


class _GcpClient:
    def access_secret_version(self, *, request):
        assert request["name"].endswith("/versions/latest")
        return SimpleNamespace(payload=SimpleNamespace(data=b"gcp-value"))

    def get_secret(self, *, request):
        return SimpleNamespace(name=request["name"])

    def add_secret_version(self, *, request):
        assert request["payload"]["data"] == b"new-value"
        return SimpleNamespace(name=f"{request['parent']}/versions/7")


class _AzureClient:
    def get_secret(self, name, version):
        assert (name, version) == (cloud_secret_id("path/name"), None)
        return SimpleNamespace(value="azure-value")

    def set_secret(self, name, value):
        assert (name, value) == (cloud_secret_id("path/name"), "new-value")
        return SimpleNamespace(properties=SimpleNamespace(version="8"))


class _AwsClient:
    def get_secret_value(self, **request):
        assert request == {"SecretId": "path/name", "VersionStage": "AWSCURRENT"}
        return {"SecretString": "aws-value"}

    def put_secret_value(self, **request):
        assert request == {"SecretId": "path/name", "SecretString": "new-value"}
        return {"VersionId": "9"}


@pytest.mark.parametrize(
    ("provider", "reference", "expected", "version"),
    [
        (
            GcpSecretManagerProvider(project_id="project", client=_GcpClient()),
            SecretReference(provider="gcp_secret_manager", name="path/name", version="latest"),
            "gcp-value",
            "7",
        ),
        (
            AzureKeyVaultProvider(vault_url="https://vault.example", client=_AzureClient()),
            SecretReference(provider="azure_key_vault", name="path/name", version="latest"),
            "azure-value",
            "8",
        ),
        (
            AwsSecretsManagerProvider(region="eu-west-2", client=_AwsClient()),
            SecretReference(provider="aws_secrets_manager", name="path/name", version="latest"),
            "aws-value",
            "9",
        ),
    ],
)
async def test_cloud_provider_resolve_and_write(provider, reference, expected, version) -> None:
    assert await provider.resolve_secret(reference) == expected
    written = await provider.write_secret(reference.name, "new-value")
    assert written.provider == provider.provider_key
    assert written.name == reference.name
    assert written.version == version
