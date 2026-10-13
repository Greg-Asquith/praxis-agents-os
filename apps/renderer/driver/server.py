# apps/renderer/driver/server.py

"""HTTP front end: one request at a time, each in a fresh private directory."""

import hmac
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from driver.child import ChildResult, kill_stray_processes, run_child
from driver.isolation import ChildLimits, IsolationError, make_driver_undumpable
from driver.self_check import check_isolation
from driver.transfer import (
    SignedTransfer,
    TransferError,
    TransferTimeoutError,
    download,
    require_allowed_url,
    upload,
)

MAX_REQUEST_BYTES = 64 * 1024
MAX_INPUTS = 10
HEADER_NAME = re.compile(r"^[a-z0-9-]{1,64}$")


class OperationError(Exception):
    """A failure reported to the caller with a stable code and a plain message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DriverConfig:
    allowed_url_prefixes: tuple[str, ...]
    max_input_bytes: int
    max_output_bytes: int
    max_timeout_seconds: int
    child_memory_bytes: int
    # Empty when the platform authenticates callers, as Cloud Run IAM does.
    shared_secret: str = ""

    @classmethod
    def from_environment(cls) -> "DriverConfig":
        prefixes = tuple(
            prefix.strip()
            for prefix in os.environ.get("RENDERER_ALLOWED_URL_PREFIXES", "").split(",")
            if prefix.strip()
        )
        if not prefixes or any(not prefix.endswith("/") for prefix in prefixes):
            raise SystemExit("RENDERER_ALLOWED_URL_PREFIXES must list URL prefixes ending in /")
        shared_secret = os.environ.get("RENDERER_SHARED_SECRET", "")
        if shared_secret and len(shared_secret) < 32:
            raise SystemExit("RENDERER_SHARED_SECRET must be at least 32 characters")
        return cls(
            allowed_url_prefixes=prefixes,
            max_input_bytes=int(os.environ.get("RENDERER_MAX_INPUT_BYTES", 5 * 1024**3)),
            max_output_bytes=int(os.environ.get("RENDERER_MAX_OUTPUT_BYTES", 500 * 1024**2)),
            max_timeout_seconds=int(os.environ.get("RENDERER_MAX_TIMEOUT_SECONDS", 900)),
            child_memory_bytes=int(os.environ.get("RENDERER_CHILD_MEMORY_BYTES", 8 * 1024**3)),
            shared_secret=shared_secret,
        )


@dataclass
class OperationContext:
    """What an operation may use: its input, its directory, and isolated children."""

    config: DriverConfig
    workdir: Path
    inputs: list[tuple[SignedTransfer, int]]
    output_count: int
    deadline: float
    _fetched: set[int] = field(default_factory=set)

    def input_path(self, index: int = 0) -> Path:
        if not 0 <= index < len(self.inputs):
            raise IndexError(index)
        return self.workdir / f"input-{index}"

    def output_path(self, index: int) -> Path:
        if not 0 <= index < self.output_count:
            raise IndexError(index)
        return self.workdir / f"output-{index}"

    def fetch_input(self, index: int = 0) -> Path:
        """Downloads one whole input once, within the request's deadline."""
        path = self.input_path(index)
        if index in self._fetched:
            return path
        self.remaining_seconds()
        transfer, size_bytes = self.inputs[index]
        try:
            download(transfer, path, size_bytes=size_bytes, deadline=self.deadline)
        except TransferError as exc:
            raise _transfer_error(exc, "The input couldn't be downloaded.") from exc
        self._fetched.add(index)
        return path

    def remaining_seconds(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OperationError("timeout", "The operation ran out of time.")
        return remaining

    def run(self, argv: list[str]) -> ChildResult:
        """Runs a native command isolated and within the request's remaining time."""
        timeout = self.remaining_seconds()
        result = run_child(
            argv,
            workdir=self.workdir,
            limits=ChildLimits(
                memory_bytes=self.config.child_memory_bytes,
                cpu_seconds=max(1, int(timeout) * (os.cpu_count() or 1)),
                max_file_bytes=self.config.max_output_bytes,
            ),
            timeout_seconds=timeout,
        )
        if result.timed_out:
            raise OperationError("timeout", "The operation ran out of time.")
        return result


@dataclass(frozen=True)
class Operation:
    """A typed operation a toolchain offers.

    ``validate`` returns the arguments or raises OperationError; it sees only
    numbers and booleans. ``output_count`` and ``input_count`` say how many
    signed uploads and downloads the caller must provide. ``run`` writes
    outputs by index and returns the result.
    """

    validate: Callable[[dict[str, Any]], dict[str, Any]]
    output_count: Callable[[dict[str, Any]], int]
    run: Callable[[OperationContext, dict[str, Any]], dict[str, Any]]
    input_count: Callable[[dict[str, Any]], int] = lambda arguments: 1


def handle_request(
    payload: Any, *, config: DriverConfig, operations: dict[str, Operation]
) -> dict[str, Any]:
    """Validates a request, runs its operation in a fresh directory, and uploads outputs.

    timeout_seconds bounds the whole request: downloads, children, and uploads.
    """
    started = time.monotonic()
    request = _parse_request(payload, config=config, operations=operations)
    operation = operations[request["operation"]]
    workdir = Path(tempfile.mkdtemp(prefix="request-"))
    try:
        context = OperationContext(
            config=config,
            workdir=workdir,
            inputs=request["inputs"],
            output_count=len(request["outputs"]),
            deadline=started + request["timeout_seconds"],
        )
        result = operation.run(context, request["arguments"])
        return {
            "ok": True,
            "result": result,
            "outputs": _upload_outputs(context, request["outputs"]),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    finally:
        _clean_up(workdir)


def _upload_outputs(
    context: OperationContext, transfers: list[SignedTransfer]
) -> list[dict[str, Any]]:
    outputs = []
    for index, transfer in enumerate(transfers):
        path = context.output_path(index)
        if not path.is_file() or path.is_symlink():
            raise OperationError("missing_output", "The operation produced no output.")
        if path.stat().st_size > context.config.max_output_bytes:
            raise OperationError("output_too_large", "The output is too large.")
        try:
            size, digest = upload(transfer, path, deadline=context.deadline)
        except TransferError as exc:
            raise _transfer_error(exc, "The output couldn't be uploaded.") from exc
        outputs.append({"size_bytes": size, "sha256": digest})
    return outputs


def _clean_up(workdir: Path) -> None:
    try:
        kill_stray_processes()
    except IsolationError as exc:
        # A survivor could reach the next request, so retire this instance instead.
        print(json.dumps({"message": "isolation lost", "reason": str(exc)}), flush=True)  # noqa: T201
        os._exit(1)
    shutil.rmtree(workdir, ignore_errors=True)


def _transfer_error(exc: TransferError, message: str) -> OperationError:
    if isinstance(exc, TransferTimeoutError):
        return OperationError("timeout", "The operation ran out of time.")
    return OperationError("transfer_failed", message)


def _parse_request(
    payload: Any, *, config: DriverConfig, operations: dict[str, Operation]
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "operation",
        "timeout_seconds",
        "inputs",
        "outputs",
        "arguments",
    }:
        raise OperationError("invalid_request", "The request has the wrong fields.")
    operation = (
        operations.get(payload["operation"]) if isinstance(payload["operation"], str) else None
    )
    if operation is None:
        raise OperationError("invalid_request", "Unknown operation.")
    timeout = payload["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= config.max_timeout_seconds:
        raise OperationError("invalid_request", "timeout_seconds is out of range.")
    arguments = payload["arguments"]
    if not isinstance(arguments, dict):
        raise OperationError("invalid_request", "arguments must be an object.")
    arguments = operation.validate(arguments)
    inputs = payload["inputs"]
    if (
        not isinstance(inputs, list)
        or not 1 <= len(inputs) <= MAX_INPUTS
        or len(inputs) != operation.input_count(arguments)
    ):
        raise OperationError("invalid_request", "The request has the wrong number of inputs.")
    outputs = payload["outputs"]
    if not isinstance(outputs, list) or len(outputs) != operation.output_count(arguments):
        raise OperationError("invalid_request", "The request has the wrong number of outputs.")
    return {
        "operation": payload["operation"],
        "timeout_seconds": timeout,
        "inputs": _parse_inputs(inputs, config),
        "outputs": [_parse_transfer(item, config) for item in outputs],
        "arguments": arguments,
    }


def _parse_inputs(inputs: list[Any], config: DriverConfig) -> list[tuple[SignedTransfer, int]]:
    """Parses each signed download and its size; together they must fit the input limit."""
    parsed = []
    for source in inputs:
        if not isinstance(source, dict) or set(source) != {"url", "headers", "size_bytes"}:
            raise OperationError("invalid_request", "An input has the wrong fields.")
        size = source["size_bytes"]
        if type(size) is not int or size < 1:
            raise OperationError("invalid_request", "An input has the wrong size.")
        parsed.append((_parse_transfer(source, config, extra_keys={"size_bytes"}), size))
    # Inputs share the instance's in-memory disk, so the limit covers them together.
    if sum(size for _, size in parsed) > config.max_input_bytes:
        raise OperationError("input_too_large", "The input is too large for the renderer.")
    return parsed


def _parse_transfer(
    value: Any, config: DriverConfig, *, extra_keys: frozenset[str] | set[str] = frozenset()
) -> SignedTransfer:
    if not isinstance(value, dict) or set(value) != {"url", "headers", *extra_keys}:
        raise OperationError("invalid_request", "A transfer has the wrong fields.")
    url, headers = value["url"], value["headers"]
    if not isinstance(url, str) or not isinstance(headers, dict):
        raise OperationError("invalid_request", "A transfer has the wrong fields.")
    try:
        require_allowed_url(url, config.allowed_url_prefixes)
    except TransferError as exc:
        raise OperationError("invalid_request", "A transfer URL isn't allowed.") from exc
    for name, header in headers.items():
        if (
            not isinstance(header, str)
            or not HEADER_NAME.match(name)
            or any(char in header for char in "\r\n\0")
        ):
            raise OperationError("invalid_request", "A transfer header isn't allowed.")
    return SignedTransfer(url=url, headers=dict(headers))


class _Handler(BaseHTTPRequestHandler):
    server: "RendererServer"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(HTTPStatus.OK, {"ok": True})
            return
        self._send(HTTPStatus.NOT_FOUND, {"ok": False})

    def do_POST(self) -> None:
        if self.path != "/v1/operations":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False})
            return
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, _error("unauthorized", "Not authorized."))
            return
        header = self.headers.get("content-length") or ""
        length = int(header) if header.isascii() and header.isdigit() else 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._send(HTTPStatus.BAD_REQUEST, _error("invalid_request", "Bad request size."))
            return
        try:
            payload = json.loads(self.rfile.read(length))
            response = handle_request(
                payload, config=self.server.config, operations=self.server.operations
            )
            self._send(HTTPStatus.OK, response)
        except json.JSONDecodeError:
            self._send(HTTPStatus.BAD_REQUEST, _error("invalid_request", "Bad JSON."))
        except OperationError as exc:
            status = HTTPStatus.BAD_REQUEST if exc.code == "invalid_request" else HTTPStatus.OK
            self._send(status, _error(exc.code, exc.message))
        except Exception:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, _error("internal", "The renderer failed."))

    def _authorized(self) -> bool:
        secret = self.server.config.shared_secret
        if not secret:
            return True
        supplied = (self.headers.get("authorization") or "").encode()
        return hmac.compare_digest(supplied, f"Bearer {secret}".encode())

    def log_message(self, format: str, *args: Any) -> None:
        # Request lines carry no signed URLs, but keep logs to status codes.
        return

    def _send(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


class RendererServer(HTTPServer):
    """Single-threaded on purpose: one request per instance at a time."""

    def __init__(
        self, address: tuple[str, int], *, config: DriverConfig, operations: dict[str, Operation]
    ) -> None:
        super().__init__(address, _Handler)
        self.config = config
        self.operations = operations


def serve(operations: dict[str, Operation]) -> None:
    """Runs the self-check, then serves until stopped. Exits if isolation is unavailable."""
    config = DriverConfig.from_environment()
    make_driver_undumpable()
    try:
        check_isolation()
    except IsolationError as exc:
        print(  # noqa: T201
            json.dumps({"message": "isolation unavailable", "reason": str(exc)}), flush=True
        )
        raise SystemExit(1) from exc
    server = RendererServer(
        # Cloud Run routes to 0.0.0.0:$PORT.
        ("0.0.0.0", int(os.environ.get("PORT", "8080"))),  # noqa: S104
        config=config,
        operations=operations,
    )
    print(json.dumps({"message": "renderer ready", "isolation": "verified"}), flush=True)  # noqa: T201
    server.serve_forever()
