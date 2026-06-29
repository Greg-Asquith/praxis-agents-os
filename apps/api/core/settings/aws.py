# apps/api/core/settings/aws.py

"""AWS infrastructure provider settings."""

from pydantic import Field, SecretStr


class AwsSettingsMixin:
    # AWS S3 Storage Configuration
    S3_PUBLIC_ASSETS_BUCKET: str = Field(
        default="",
        description="S3 bucket for public assets. Required when STORAGE_PROVIDER=s3.",
    )
    S3_PRIVATE_ASSETS_BUCKET: str = Field(
        default="",
        description="S3 bucket for private originals and documents. Required when STORAGE_PROVIDER=s3.",
    )

    # AWS SES Config
    SES_REGION: str = Field(default="eu-west-2", description="AWS SES region")
    SES_FROM_EMAIL: str = Field(
        default="noreply@praxis-agents.ai", description="AWS SES from email"
    )
    SES_CONFIGURATION_SET: str = Field(default="", description="AWS SES configuration set")
    AWS_ACCESS_KEY_ID: str = Field(default="", description="AWS access key ID")
    AWS_SECRET_ACCESS_KEY: SecretStr = Field(
        default=SecretStr(""), description="AWS secret access key"
    )
