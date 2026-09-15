"""Download diagnostics stay private without suppressing concurrent requests."""

import asyncio
import logging

from services.integrations.microsoft_graph.download_logging import suppress_download_logging


async def test_download_filter_is_task_local_and_resets_after_failure(caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx2")
    started, release = asyncio.Event(), asyncio.Event()

    async def download():
        try:
            with suppress_download_logging():
                started.set()
                await release.wait()
                for name in (
                    "httpx2",
                    "httpcore2.http11",
                    "httpcore2.http2",
                    "httpcore2.connection",
                    "httpcore2.proxy",
                    "httpcore2.socks",
                ):
                    logging.getLogger(name).debug("PRIVATE_DOWNLOAD_SECRET")
                raise ValueError("safe failure")
        except ValueError:
            logging.getLogger("httpx2").info("After download")

    task = asyncio.create_task(download())
    await started.wait()
    logging.getLogger("httpx2").info("Concurrent request")
    release.set()
    await task
    assert "PRIVATE_DOWNLOAD_SECRET" not in caplog.text
    assert "Concurrent request" in caplog.text and "After download" in caplog.text
