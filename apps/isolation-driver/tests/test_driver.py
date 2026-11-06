# apps/isolation-driver/tests/test_driver.py

"""Driver request handling: the operation deadline and the HTTP request boundary."""

import http.client
import json
import threading

import pytest
from driver import transfer
from driver.server import DriverConfig, Operation, OperationError, RendererServer, handle_request
from driver_testing.plugin import FakeStorage

# Stand-ins for a toolchain's operations: one reads its input, one takes its data inline.
OPERATIONS = {
    "size": Operation(
        validate=lambda arguments: arguments,
        output_count=lambda arguments: 0,
        run=lambda context, arguments: {"size_bytes": context.fetch_input().stat().st_size},
    ),
    "total": Operation(
        validate=lambda arguments: arguments,
        output_count=lambda arguments: 0,
        run=lambda context, arguments: {"total": sum(arguments["values"])},
        input_count=lambda arguments: 0,
    ),
}


class _EndlessResponse:
    """A download that keeps sending chunks while the clock moves on."""

    status = 200

    def __init__(self, clock: list[float]) -> None:
        self._clock = clock

    def read(self, size: int) -> bytes:
        self._clock[0] += 61
        return b"\0" * 1024

    def __enter__(self) -> "_EndlessResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_a_progressing_download_stops_at_the_deadline(
    storage: FakeStorage, config: DriverConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.objects["input.bin"] = b"\0" * 1024
    request = {
        "operation": "size",
        "timeout_seconds": 60,
        "inputs": [storage.source("input.bin")],
        "outputs": [],
        "arguments": {},
    }
    clock = [0.0]
    with monkeypatch.context() as patch:
        # The driver and transfers share the time module, so this moves both clocks.
        patch.setattr(transfer.time, "monotonic", lambda: clock[0])
        patch.setattr(transfer, "_open", lambda request, deadline: _EndlessResponse(clock))
        with pytest.raises(OperationError) as error:
            handle_request(request, config=config, operations=OPERATIONS)

    assert error.value.code == "timeout"
    assert handle_request(request, config=config, operations=OPERATIONS)["ok"] is True


def test_requests_need_the_shared_secret_when_one_is_set(config: DriverConfig) -> None:
    secret = "s" * 32
    server = RendererServer(
        ("127.0.0.1", 0),
        config=DriverConfig(**{**config.__dict__, "shared_secret": secret}),
        operations=OPERATIONS,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        refused = [
            _post(server, {"Authorization": value, "Content-Length": "2"}, b"{}")
            for value in ("", "Bearer " + "t" * 32)
        ]
        accepted = _post(
            server, {"Authorization": f"Bearer {secret}", "Content-Length": "2"}, b"{}"
        )
        malformed = _post(server, {"Authorization": f"Bearer {secret}", "Content-Length": "ten"})
    finally:
        server.shutdown()
        server.server_close()

    assert [(status, body["error"]["code"]) for status, body in refused] == [
        (401, "unauthorized"),
        (401, "unauthorized"),
    ]
    # Past authentication, both reach validation; a bad Content-Length gets a structured error.
    for status, body in (accepted, malformed):
        assert (status, body["error"]["code"]) == (400, "invalid_request")


def test_only_a_zero_input_operation_runs_without_inputs(config: DriverConfig) -> None:
    def request(operation: str) -> dict:
        return {
            "operation": operation,
            "timeout_seconds": 10,
            "inputs": [],
            "outputs": [],
            "arguments": {"values": [1, 2]},
        }

    with pytest.raises(OperationError) as error:
        handle_request(request("size"), config=config, operations=OPERATIONS)

    assert error.value.code == "invalid_request"
    assert handle_request(request("total"), config=config, operations=OPERATIONS)["result"] == {
        "total": 3
    }


def test_a_request_over_the_services_size_cap_is_refused(config: DriverConfig) -> None:
    server = RendererServer(
        ("127.0.0.1", 0), config=config, operations=OPERATIONS, max_request_bytes=1024
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "operation": "total",
                "timeout_seconds": 10,
                "inputs": [],
                "outputs": [],
                "arguments": {"values": [1] * 1000},
            }
        ).encode()
        within = _post(server, {"Content-Length": "1024"}, body[:1024])
        over = _post(server, {"Content-Length": str(len(body))}, body)
    finally:
        server.shutdown()
        server.server_close()

    # The truncated body passes the size check and fails as JSON instead.
    assert within[1]["error"]["message"] == "Bad JSON."
    assert over[1]["error"]["message"] == "Bad request size."


def _post(server: RendererServer, headers: dict[str, str], body: bytes = b"") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    connection.putrequest("POST", "/v1/operations")
    for name, value in headers.items():
        connection.putheader(name, value)
    connection.endheaders(body or None)
    response = connection.getresponse()
    return response.status, json.loads(response.read())
