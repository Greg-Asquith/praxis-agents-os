# apps/api/tests/support/anthropic.py

"""Anthropic Messages API mock responses."""

import json

import httpx2 as httpx


def anthropic_message_response(request: httpx.Request, message: dict) -> httpx.Response:
    """Returns the message as JSON, or as SSE when Pydantic AI streams the request behind the scenes."""
    if not json.loads(request.content).get("stream"):
        return httpx.Response(200, json=message)
    events = [
        ("message_start", {"message": {**message, "content": [], "stop_reason": None}}),
    ]
    for index, block in enumerate(message["content"]):
        if block["type"] == "text":
            start, delta = {**block, "text": ""}, {"type": "text_delta", "text": block["text"]}
        else:
            start = {**block, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        events += [
            ("content_block_start", {"index": index, "content_block": start}),
            ("content_block_delta", {"index": index, "delta": delta}),
            ("content_block_stop", {"index": index}),
        ]
    events += [
        (
            "message_delta",
            {
                "delta": {"stop_reason": message["stop_reason"]},
                "usage": {"output_tokens": message["usage"]["output_tokens"]},
            },
        ),
        ("message_stop", {}),
    ]
    body = "".join(
        f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n" for name, data in events
    )
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
