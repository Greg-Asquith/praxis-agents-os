# apps/api/tests/services/test_pagination.py

"""Tests for shared service pagination helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from tests.factories.users import build_user
from utils.pagination import paginate


async def test_paginate_counts_filtered_rows_not_window(db_session: AsyncSession) -> None:
    page_emails = ["page-a@example.com", "page-b@example.com", "page-c@example.com"]
    users = [
        build_user(email=page_emails[0], display_name="A"),
        build_user(email=page_emails[1], display_name="B"),
        build_user(email=page_emails[2], display_name="C"),
        build_user(email="page-other@example.net", display_name="Other"),
    ]
    db_session.add_all(users)
    await db_session.flush()

    page, total = await paginate(
        db_session,
        select(User).where(User.email.in_(page_emails)),
        User.email.asc(),
        limit=2,
        offset=1,
    )

    assert total == 3
    assert [user.email for user in page] == ["page-b@example.com", "page-c@example.com"]


async def test_paginate_empty_result_returns_empty_list_and_zero_total(
    db_session: AsyncSession,
) -> None:
    page, total = await paginate(
        db_session,
        select(User).where(User.email == "missing@example.com"),
        User.email.asc(),
        limit=10,
        offset=0,
    )

    assert page == []
    assert total == 0
