# apps/api/core/settings/auth.py

"""OAuth provider and email authentication settings."""

from pydantic import Field, SecretStr, model_validator


class AuthSettingsMixin:
    # OAuth Configuration
    OAUTH_REQUEST_TIMEOUT: int = Field(
        default=30, ge=5, le=120, description="OAuth HTTP request timeout in seconds"
    )
    OAUTH_MAX_RETRIES: int = Field(
        default=3, ge=1, le=10, description="Maximum number of OAuth request retries"
    )
    OAUTH_BACKOFF_FACTOR: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Exponential backoff factor for OAuth retries",
    )

    EMAIL_AUTH_ENABLED: bool = Field(default=True, description="Enable email/password auth flows")

    # OAuth Login Providers Configuration (Auth)

    GOOGLE_OAUTH_ENABLED: bool = Field(default=False, description="Enable Google login OAuth")
    GOOGLE_OAUTH_CLIENT_ID: str = Field(default="", description="Google OAuth client ID (Login)")
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr = Field(
        default=SecretStr(""), description="Google OAuth client secret (Login)"
    )
    GOOGLE_OAUTH_REDIRECT_URI: str = Field(
        default="", description="Google OAuth redirect URI for Login"
    )

    GITHUB_OAUTH_ENABLED: bool = Field(default=False, description="Enable GitHub login OAuth")
    GITHUB_OAUTH_CLIENT_ID: str = Field(default="", description="GitHub OAuth client ID")
    GITHUB_OAUTH_CLIENT_SECRET: SecretStr = Field(
        default=SecretStr(""), description="GitHub OAuth client secret"
    )
    GITHUB_OAUTH_REDIRECT_URI: str = Field(default="", description="GitHub OAuth redirect URI")

    MICROSOFT_OAUTH_ENABLED: bool = Field(default=False, description="Enable Microsoft login OAuth")
    MICROSOFT_OAUTH_CLIENT_ID: str = Field(default="", description="Microsoft OAuth client ID")
    MICROSOFT_OAUTH_CLIENT_SECRET: SecretStr = Field(
        default=SecretStr(""), description="Microsoft OAuth client secret"
    )
    MICROSOFT_OAUTH_REDIRECT_URI: str = Field(
        default="", description="Microsoft OAuth redirect URI"
    )

    @model_validator(mode="after")
    def validate_enabled_oauth_providers(self):
        """Each enabled OAuth provider must have its client ID, secret, and redirect URI."""
        providers = (
            (
                "Google",
                self.GOOGLE_OAUTH_ENABLED,
                self.GOOGLE_OAUTH_CLIENT_ID,
                self.GOOGLE_OAUTH_CLIENT_SECRET,
                self.GOOGLE_OAUTH_REDIRECT_URI,
            ),
            (
                "GitHub",
                self.GITHUB_OAUTH_ENABLED,
                self.GITHUB_OAUTH_CLIENT_ID,
                self.GITHUB_OAUTH_CLIENT_SECRET,
                self.GITHUB_OAUTH_REDIRECT_URI,
            ),
            (
                "Microsoft",
                self.MICROSOFT_OAUTH_ENABLED,
                self.MICROSOFT_OAUTH_CLIENT_ID,
                self.MICROSOFT_OAUTH_CLIENT_SECRET,
                self.MICROSOFT_OAUTH_REDIRECT_URI,
            ),
        )
        for name, enabled, client_id, client_secret, redirect_uri in providers:
            if not enabled:
                continue
            missing = []
            if not (client_id or "").strip():
                missing.append("client ID")
            if not client_secret.get_secret_value().strip():
                missing.append("client secret")
            if not (redirect_uri or "").strip():
                missing.append("redirect URI")
            if missing:
                raise ValueError(f"{name} OAuth is enabled but missing: {', '.join(missing)}")
        return self
