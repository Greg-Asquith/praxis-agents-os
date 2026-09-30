# apps/api/services/documents/editing.py

"""The operation loop, change log, and run-level text replacement shared by document edits.

Runs only inside the document worker. Operations apply in order to the file in
memory, and the handler saves only when every one succeeds, so a failed
operation never leaves a partial revision.
"""

import re
import sys
from bisect import bisect_right
from collections.abc import Callable, Sequence
from typing import Any

from services.documents.reading import DocumentRequestError, ReadPage

type OperationHandler = Callable[[dict[str, Any], "EditLog"], None]

_MAX_WARNINGS = 50
# Warnings and changes share at most this part of the page; the read-back gets the rest.
_LOG_SHARE = 0.5


class OperationError(Exception):
    """An operation doesn't fit the document as it stands."""


class EditLog:
    """Collects what each operation changed, warnings, and the bounded read-back."""

    def __init__(self, args: dict[str, Any]) -> None:
        self.page = ReadPage(args)
        self.changes: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        # Distinct warnings past the cap, counted but not kept.
        self.warnings_dropped = 0
        self.index = 0

    def change(self, summary: str, **facts: Any) -> None:
        self.changes.append({"operation": self.index, "summary": summary, **facts})

    def warn(self, message: str) -> None:
        if message in self.warnings:
            return
        if len(self.warnings) < _MAX_WARNINGS:
            self.warnings.append(message)
        else:
            self.warnings_dropped += 1

    def result(self, readback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Returns warnings, changes, and read-back within the page budget, in that priority.

        Counts of anything left out are kept, so the caller knows to read the new
        revision for the rest.
        """
        share = int(self.page.max_chars * _LOG_SHARE)
        result: dict[str, Any] = {}
        warnings = self._bounded(self.warnings, share)
        if warnings:
            result["warnings"] = warnings
        omitted = len(self.warnings) - len(warnings) + self.warnings_dropped
        if omitted:
            result["warnings_omitted"] = omitted
        result["changes"] = self._bounded(self.changes, share)
        if len(result["changes"]) < len(self.changes):
            result["changes_omitted"] = len(self.changes) - len(result["changes"])
        result["readback"] = readback()
        return result

    def _bounded(self, items: list[Any], share: int) -> list[Any]:
        kept = []
        for item in items:
            if not self.page.fits(item, within=share):
                break
            kept.append(item)
        return kept


def run_operations(
    operations: Sequence[dict[str, Any]],
    handlers: dict[str, OperationHandler],
    log: EditLog,
) -> None:
    """Applies operations in order, failing the whole call on the first that doesn't fit."""
    for index, operation in enumerate(operations):
        log.index = index
        kind = str(operation.get("op"))
        handler = handlers.get(kind)
        try:
            if handler is None:
                raise OperationError("isn't a supported operation.")
            handler(operation, log)
        except OperationError as exc:
            raise DocumentRequestError(
                f"operations[{index}] ({kind}): {exc} Nothing was saved."
            ) from None
        except DocumentRequestError:
            raise
        except Exception as exc:
            # Library messages can quote file content, so only the type is reported.
            sys.stderr.write(f"document edit {kind} failed: {type(exc).__name__}\n")
            raise DocumentRequestError(
                f"operations[{index}] ({kind}) couldn't be applied to this file. Nothing was saved."
            ) from None


def replace_in_runs(runs: Sequence[Any], find: str, replace: str, *, match_case: bool) -> int:
    """Replaces matches across a sequence of runs with a `text` attribute, returning the count.

    A match that spans runs goes into the first run it touches, so it takes that
    run's formatting; the rest of the match is cut from the following runs.
    Runs are written only when their text changes.
    """
    texts = [run.text for run in runs]
    pattern = re.compile(re.escape(find), 0 if match_case else re.IGNORECASE)
    matches = [match.span() for match in pattern.finditer("".join(texts))]
    if not matches:
        return 0
    starts = []
    offset = 0
    for text in texts:
        starts.append(offset)
        offset += len(text)
    updated = list(texts)
    # Later matches first, so earlier offsets stay valid.
    for match_start, match_end in reversed(matches):
        first = _run_at(starts, match_start)
        last = _run_at(starts, match_end - 1)
        head = updated[first][: match_start - starts[first]]
        if first == last:
            updated[first] = head + replace + updated[first][match_end - starts[first] :]
            continue
        updated[first] = head + replace
        for middle in range(first + 1, last):
            updated[middle] = ""
        updated[last] = updated[last][match_end - starts[last] :]
    for run, before, after in zip(runs, texts, updated, strict=True):
        if before != after:
            run.text = after
    return len(matches)


def _run_at(starts: list[int], position: int) -> int:
    return bisect_right(starts, position) - 1


def split_attachments(data: bytes, args: dict[str, Any]) -> tuple[bytes, list[bytes]]:
    """Splits a request payload into the document and the attachments packed after it."""
    sizes = [int(size) for size in args.get("attachment_sizes") or []]
    end = len(data) - sum(sizes)
    if end < 0 or any(size < 0 for size in sizes):
        raise DocumentRequestError("The request's attachments don't match its payload.")
    attachments = []
    position = end
    for size in sizes:
        attachments.append(data[position : position + size])
        position += size
    return data[:end], attachments
