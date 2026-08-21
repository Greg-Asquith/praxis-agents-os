# apps/api/scripts/export_stream_protocol.py

"""Export the authoritative agent stream contract for the web client."""

import argparse
import json
from pathlib import Path

from services.agents.runtime.stream_protocol import (
    stream_protocol_samples,
    stream_protocol_schema,
)

WEB_CONTRACT_DIRECTORY = (
    Path(__file__).resolve().parents[2]
    / "web"
    / "tests"
    / "features"
    / "conversations"
    / "stream"
    / "fixtures"
)


def _render_json(value: object) -> str:
    return f"{json.dumps(value, indent=2, sort_keys=True)}\n"


def _artifacts() -> dict[Path, str]:
    return {
        WEB_CONTRACT_DIRECTORY / "protocol.schema.json": _render_json(stream_protocol_schema()),
        WEB_CONTRACT_DIRECTORY / "protocol.samples.json": _render_json(stream_protocol_samples()),
    }


def _check_artifacts() -> None:
    stale = [
        path
        for path, expected in _artifacts().items()
        if not path.exists() or path.read_text(encoding="utf-8") != expected
    ]
    if stale:
        paths = ", ".join(str(path.relative_to(WEB_CONTRACT_DIRECTORY)) for path in stale)
        raise SystemExit(
            f"Stream protocol artifacts are stale: {paths}. "
            "Run `make stream-protocol-export` from the repository root."
        )


def main() -> None:
    """Write or check the schema and samples consumed by the web client."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when checked-in artifacts are stale",
    )
    args = parser.parse_args()
    if args.check:
        _check_artifacts()
        return

    WEB_CONTRACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for path, contents in _artifacts().items():
        path.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()
