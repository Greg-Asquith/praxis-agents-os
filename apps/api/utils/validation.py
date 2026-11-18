# apps/api/utils/validation.py

"""Reusable validation helpers."""

from core.exceptions.general import AppValidationError


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_optional_text(value: str | None) -> str | None:
    """Trim optional text fields and collapse blank values to None."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def validate_email(email: str) -> None:
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise AppValidationError("Invalid email address", field="email")
    local, _, domain = email.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise AppValidationError("Invalid email address", field="email")


def validate_bare_email(email: str) -> None:
    """Accepts one address with no display name, comment, or quoting.

    Send tools compare recipients with the Do Not Email list as exact strings, so the string
    they check must be the address the provider delivers to.
    """
    validate_email(email)
    if email.count("@") != 1 or any(char.isspace() or char in '<>,;()"' for char in email):
        raise AppValidationError("Enter one email address without a display name", field="email")


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise AppValidationError("Password must be at least 8 characters", field="password")
    if password.strip() != password:
        raise AppValidationError("Password cannot start or end with whitespace", field="password")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise AppValidationError(
            "Password must contain at least one letter and one number",
            field="password",
        )
