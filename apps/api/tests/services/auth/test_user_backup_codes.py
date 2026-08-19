"""User backup-code sync and async behavior."""

import pytest

import models.user as user_module
from models.user import User


@pytest.mark.asyncio
async def test_sync_and_async_backup_code_paths_share_state_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def hash_password(password: str) -> str:
        return f"hashed:{password}"

    async def hash_passwords_async(passwords: list[str]) -> list[str]:
        return [hash_password(password) for password in passwords]

    def verify_password_hash(password: str, hashed_password: str) -> bool:
        return hashed_password == hash_password(password)

    async def matching_password_hash_index_async(
        password: str,
        hashed_passwords: list[str],
    ) -> int | None:
        expected = hash_password(password)
        return next(
            (
                index
                for index, hashed_password in enumerate(hashed_passwords)
                if hashed_password == expected
            ),
            None,
        )

    monkeypatch.setattr(user_module, "hash_password", hash_password)
    monkeypatch.setattr(user_module, "hash_passwords_async", hash_passwords_async)
    monkeypatch.setattr(user_module, "verify_password_hash", verify_password_hash)
    monkeypatch.setattr(
        user_module,
        "matching_password_hash_index_async",
        matching_password_hash_index_async,
    )

    user = User(email="backup-codes@example.com", display_name="Backup Codes", is_active=True)

    sync_codes = user.generate_backup_codes()
    assert len(sync_codes) == 8
    assert user.verify_backup_code(sync_codes[0]) is True
    assert user.backup_codes_remaining == 7
    assert user.verify_backup_code(sync_codes[0]) is False

    async_codes = await user.generate_backup_codes_async()
    assert len(async_codes) == 8
    assert await user.verify_backup_code_async(async_codes[0]) is True
    assert user.backup_codes_remaining == 7
    assert await user.verify_backup_code_async(async_codes[0]) is False
