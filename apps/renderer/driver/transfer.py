# apps/renderer/driver/transfer.py

"""Signed URL transfers. The driver is the only part of the renderer with network access."""

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CHUNK_BYTES = 1024 * 1024
# Longest one blocking read or write may wait, so a stalled transfer ends soon after
# its deadline; Cloud Run's request timeout leaves 60 seconds over the deadline.
IDLE_TIMEOUT_SECONDS = 30


class TransferError(RuntimeError):
    """Raised when a signed transfer is refused or fails."""


class TransferTimeoutError(TransferError):
    """Raised when a transfer reaches the operation's deadline."""


@dataclass(frozen=True)
class SignedTransfer:
    url: str
    headers: dict[str, str]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransferError("Signed transfer was redirected")


# Ignores proxy environment variables and refuses redirects to other hosts.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def require_allowed_url(url: str, allowed_prefixes: tuple[str, ...]) -> None:
    """Refuses any URL outside the configured storage endpoints."""
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or parts.username or parts.password:
        raise TransferError("Transfer URL is not allowed")
    if not any(url.startswith(prefix) for prefix in allowed_prefixes):
        raise TransferError("Transfer URL is not allowed")


def download(transfer: SignedTransfer, path: Path, *, size_bytes: int, deadline: float) -> None:
    """Downloads exactly size_bytes to path before the monotonic deadline."""
    request = urllib.request.Request(transfer.url, headers=transfer.headers, method="GET")  # noqa: S310
    with _open(request, deadline) as response, path.open("wb") as handle:
        if response.status != 200:
            raise TransferError(f"Download returned HTTP {response.status}")
        written = 0
        try:
            while chunk := response.read(CHUNK_BYTES):
                _require_time(deadline)
                written += len(chunk)
                if written > size_bytes:
                    raise TransferError("Transfer is larger than declared")
                handle.write(chunk)
        except OSError as exc:
            raise TransferError("Download failed") from exc
    if written != size_bytes:
        raise TransferError("Download size doesn't match the input")


def upload(transfer: SignedTransfer, path: Path, *, deadline: float) -> tuple[int, str]:
    """Uploads path before the monotonic deadline and returns its size and SHA-256."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        body = _TimedReader(handle, deadline)
        request = urllib.request.Request(  # noqa: S310
            transfer.url,
            data=body,
            headers={**transfer.headers, "content-length": str(size)},
            method="PUT",
        )
        with _open(request, deadline) as response:
            if response.status not in {200, 201, 204}:
                raise TransferError(f"Upload returned HTTP {response.status}")
    if body.sent != size:
        raise TransferError("Upload size doesn't match the output")
    return size, body.digest.hexdigest()


class _TimedReader:
    """Request body that hashes what it sends and stops at the deadline."""

    def __init__(self, handle, deadline: float) -> None:
        self._handle = handle
        self._deadline = deadline
        self.digest = hashlib.sha256()
        self.sent = 0

    def read(self, size: int = CHUNK_BYTES) -> bytes:
        _require_time(self._deadline)
        chunk = self._handle.read(min(size, CHUNK_BYTES) if size > 0 else CHUNK_BYTES)
        self.digest.update(chunk)
        self.sent += len(chunk)
        return chunk


def _require_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransferTimeoutError("Transfer reached the operation deadline")
    return remaining


def _open(request: urllib.request.Request, deadline: float):
    timeout = min(IDLE_TIMEOUT_SECONDS, _require_time(deadline))
    try:
        # require_allowed_url limits every URL to http(s) storage prefixes.
        return _OPENER.open(request, timeout=timeout)
    except TransferError:
        raise
    except urllib.error.HTTPError as exc:
        raise TransferError(f"Transfer returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TransferError("Transfer failed") from exc


__all__ = ["SignedTransfer", "TransferError", "TransferTimeoutError", "download", "upload"]
