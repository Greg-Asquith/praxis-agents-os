# apps/api/utils/pagination.py

"""Shared offset pagination for list services."""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class OffsetPage(BaseModel):
    """Envelope fields shared by offset-paginated list responses."""

    total: int
    limit: int
    offset: int


async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    *order_by: Any,
    limit: int,
    offset: int,
    scalars: bool = True,
) -> tuple[list[Any], int]:
    """Run the count and windowed query for one offset-paginated list."""
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    result = await db.execute(stmt.order_by(*order_by).limit(limit).offset(offset))
    items = result.scalars().all() if scalars else result.all()
    return list(items), total or 0
