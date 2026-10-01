"""Document worker pools for tests, with the probe handlers loaded."""

from collections.abc import AsyncIterator, Callable

import pytest_asyncio

from services.documents.precheck import PackageLimits
from services.documents.worker import DocumentWorkerPool

_MIB = 1024 * 1024

type _PoolFactory = Callable[..., DocumentWorkerPool]


@pytest_asyncio.fixture
async def make_pool() -> AsyncIterator[_PoolFactory]:
    pools: list[DocumentWorkerPool] = []

    def build(
        *, timeout_seconds: float = 60.0, memory_bytes: int = 1024 * _MIB
    ) -> DocumentWorkerPool:
        pool = DocumentWorkerPool(
            workers=1,
            timeout_seconds=timeout_seconds,
            memory_bytes=memory_bytes,
            max_source_bytes=50 * _MIB,
            limits=PackageLimits(
                max_entries=5_000, max_uncompressed_bytes=200 * _MIB, max_compression_ratio=100
            ),
            handlers="tests.support.document_worker_probes",
        )
        pools.append(pool)
        return pool

    yield build
    for pool in pools:
        await pool.close()


@pytest_asyncio.fixture
async def pool(make_pool: _PoolFactory) -> DocumentWorkerPool:
    return make_pool()
