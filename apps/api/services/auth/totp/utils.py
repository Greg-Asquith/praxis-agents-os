# apps/api/services/auth/totp/utils.py

"""Shared TOTP authentication helpers."""

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


async def verify_and_consume_login_second_factor(
    db: AsyncSession,
    *,
    user: User,
    token: str | None,
    backup_code: str | None,
) -> bool:
    """Verify login TOTP with atomic replay protection, or consume a backup code."""
    if token:
        counter = user.matching_totp_counter(token)
        if counter is not None:
            result = await db.execute(
                update(User)
                .where(
                    User.id == user.id,
                    or_(
                        User.last_totp_counter.is_(None),
                        User.last_totp_counter < counter,
                    ),
                )
                .values(last_totp_counter=counter)
                .returning(User.id)
            )
            return result.scalar_one_or_none() is not None

    return bool(backup_code and user.verify_backup_code(backup_code))
