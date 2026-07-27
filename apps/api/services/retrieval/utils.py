# apps/api/services/retrieval/utils.py

"""Shared retrieval-engine helpers."""

from sqlalchemy import Integer, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


async def configure_hnsw_search(
    db: AsyncSession,
    *,
    ef_search: int,
) -> None:
    """Enable filtered iterative HNSW search for the current transaction."""
    await db.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
    await db.execute(
        text("SET LOCAL hnsw.ef_search = :ef").bindparams(
            bindparam(
                "ef",
                value=ef_search,
                type_=Integer(),
                literal_execute=True,
            )
        )
    )
