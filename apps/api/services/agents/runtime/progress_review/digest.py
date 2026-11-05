# apps/api/services/agents/runtime/progress_review/digest.py

"""Builds the bounded text a progress reviewer judges, without tool result bodies."""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import (
    ERROR_OUTCOMES,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from services.agents.runtime.completion_contract import completion_contract_from_run_metadata
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review.verdict import STEER_METADATA_KEY
from services.agents.runtime.untrusted import UntrustedContent, frame_untrusted_content

DIGEST_MAX_CHARS = 12_000
_TASK_MAX_CHARS = 2_000
_INSTRUCTIONS_MAX_CHARS = 600
_CRITERIA_MAX_CHARS = 1_000
_LAST_TEXT_MAX_CHARS = 600
_ARG_VALUE_MAX_CHARS = 80
_ARGS_MAX_CHARS = 300
_ERROR_MAX_CHARS = 200
_TOOL_NAME_MAX_CHARS = 64
_HEAD_CALLS = 10
_SIGNAL_THRESHOLD = 3


@dataclass(frozen=True)
class RunView:
    """The parts of one run that a digest describes."""

    agent_name: str
    instructions: str
    messages: Sequence[ModelMessage]
    completion_criteria: tuple[str, ...] = ()

    @classmethod
    def from_deps(cls, deps: RuntimeDeps, messages: Sequence[ModelMessage]) -> "RunView":
        contract = completion_contract_from_run_metadata(deps.run.metadata_json)
        return cls(
            agent_name=deps.agent.name or "Agent",
            instructions=deps.agent.instructions or "",
            messages=messages,
            completion_criteria=tuple(contract.criteria) if contract else (),
        )


@dataclass(frozen=True)
class ProgressDigest:
    text: str
    # The strongest deterministic signal, appended to steer instructions.
    signal: str | None


@dataclass
class _Call:
    name: str
    args: str
    key: str
    outcome: str = "no result yet"
    detail: str = ""


def build_progress_digest(
    run: RunView,
    *,
    root: RunView | None,
    requests: int,
    step_limit: int,
    reviews_used: int,
) -> ProgressDigest:
    """Describes the run, and the delegating root run when a specialist hit the limit."""
    task, calls, responses_since_new_call, last_text = _read_turn(run.messages)
    signals = _signals(calls, responses_since_new_call)
    ledger_budget = DIGEST_MAX_CHARS // (3 if root is None else 5)
    sections = []
    if root is not None:
        root_task, root_calls, _, _ = _read_turn(root.messages)
        sections.append(_run_section("Delegating run", root, root_task, root_calls, ledger_budget))
        sections.append(
            _run_section(
                "Specialist at the step limit", run, task, calls, ledger_budget, framed=True
            )
        )
    else:
        sections.append(_run_section("Run", run, task, calls, ledger_budget))
    sections.append(
        f"Progress: {requests} model requests used. The step limit is {step_limit}. "
        f"Earlier progress reviews: {reviews_used}."
    )
    sections.append(
        "Signals:\n" + ("\n".join(f"- {signal}" for signal in signals) if signals else "- None")
    )
    if last_text:
        sections.append(
            "Latest agent message:\n"
            + _frame("agent_message", _clip(last_text, _LAST_TEXT_MAX_CHARS))
        )
    return ProgressDigest(
        text=_bounded("\n\n".join(sections), DIGEST_MAX_CHARS),
        signal=signals[0] if signals else None,
    )


def _read_turn(
    messages: Sequence[ModelMessage],
) -> tuple[str, list[_Call], int, str]:
    start, task = _turn_start(messages)
    calls: dict[str, _Call] = {}
    seen: set[str] = set()
    responses_since_new_call = 0
    last_text = ""
    for message in messages[start:]:
        if isinstance(message, ModelResponse):
            responses_since_new_call += 1
            text = " ".join(part.content for part in message.parts if isinstance(part, TextPart))
            last_text = text.strip() or last_text
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    call = _call(part)
                    calls[part.tool_call_id] = call
                    if call.key not in seen:
                        seen.add(call.key)
                        responses_since_new_call = 0
        else:
            for part in message.parts:
                _record_result(calls, part)
    return task, list(calls.values()), responses_since_new_call, last_text


def _turn_start(messages: Sequence[ModelMessage]) -> tuple[int, str]:
    """Finds the latest prompt from a person, skipping progress-check steer messages."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, ModelRequest) or (message.metadata or {}).get(
            STEER_METADATA_KEY
        ):
            continue
        prompts = [_prompt_text(part) for part in message.parts if isinstance(part, UserPromptPart)]
        prompts = [text for text in prompts if text]
        if prompts:
            return index, "\n".join(prompts)
    return 0, ""


def _prompt_text(part: UserPromptPart) -> str:
    if isinstance(part.content, str):
        return part.content.strip()
    return " ".join(item for item in part.content if isinstance(item, str)).strip()


def _call(part: ToolCallPart) -> _Call:
    args = part.args_as_dict()
    key = json.dumps([part.tool_name, args], sort_keys=True, default=str)
    rendered = ", ".join(
        f"{name}={_clip(json.dumps(value, ensure_ascii=False, default=str), _ARG_VALUE_MAX_CHARS)}"
        for name, value in args.items()
    )
    return _Call(
        name=_clip(part.tool_name, _TOOL_NAME_MAX_CHARS),
        args=_clip(rendered, _ARGS_MAX_CHARS),
        key=key,
    )


def _record_result(calls: dict[str, _Call], part: Any) -> None:
    if isinstance(part, ToolReturnPart) and part.tool_call_id in calls:
        call = calls[part.tool_call_id]
        body = part.model_response_str(wrap_if_error=False)
        if part.outcome == "success":
            call.outcome, call.detail = "ok", f"{len(body):,} characters"
        elif part.outcome in ERROR_OUTCOMES:
            call.outcome, call.detail = "error", _clip(body, _ERROR_MAX_CHARS)
        else:
            call.outcome = part.outcome


def _signals(calls: list[_Call], responses_since_new_call: int) -> list[str]:
    signals = []
    if calls:
        key, count = Counter(call.key for call in calls).most_common(1)[0]
        if count >= _SIGNAL_THRESHOLD:
            name = next(call.name for call in calls if call.key == key)
            signals.append(f"`{name}` was called {count} times with the same arguments.")
    errors = 0
    for call in reversed(calls):
        if call.outcome != "error":
            break
        errors += 1
    if errors >= _SIGNAL_THRESHOLD:
        signals.append(f"The last {errors} tool calls failed.")
    if responses_since_new_call >= _SIGNAL_THRESHOLD:
        signals.append(f"The last {responses_since_new_call} steps made no new tool calls.")
    return signals


def _run_section(
    title: str,
    run: RunView,
    task: str,
    calls: list[_Call],
    ledger_budget: int,
    *,
    framed: bool = False,
) -> str:
    lines = [f"## {title}", f"Agent: {_clip(run.agent_name, 120)}"]
    if run.instructions:
        lines.append(
            f"Agent instructions (excerpt): {_clip(run.instructions, _INSTRUCTIONS_MAX_CHARS)}"
        )
    task_text = _clip(task, _TASK_MAX_CHARS) or "(no prompt found)"
    # A specialist's task comes from the delegating agent, so it is untrusted.
    lines.append("Task:\n" + (_frame("delegated_task", task_text) if framed else task_text))
    if run.completion_criteria:
        criteria = "\n".join(f"- {criterion}" for criterion in run.completion_criteria)
        lines.append(
            "Completion criteria:\n" + _clip(criteria, _CRITERIA_MAX_CHARS, collapse=False)
        )
    lines.append(
        f"Tool calls so far ({len(calls)}, oldest first):\n" + _ledger(calls, ledger_budget)
    )
    return "\n".join(lines)


def _ledger(calls: list[_Call], budget: int) -> str:
    if not calls:
        return "- None"
    lines = [
        f"{index}. {call.name}({call.args}) -> {call.outcome}"
        + (f": {call.detail}" if call.detail else "")
        for index, call in enumerate(calls, start=1)
    ]
    if sum(len(line) + 1 for line in lines) > budget:
        head = lines[:_HEAD_CALLS]
        tail: list[str] = []
        remaining = budget - sum(len(line) + 1 for line in head)
        for line in reversed(lines[_HEAD_CALLS:]):
            if remaining - len(line) - 1 < 0:
                break
            tail.insert(0, line)
            remaining -= len(line) + 1
        omitted = len(lines) - len(head) - len(tail)
        lines = [*head, f"[{omitted} calls omitted]", *tail]
    return _frame("tool_calls", "\n".join(lines))


def _frame(source_ref: str, content: str) -> str:
    return frame_untrusted_content(
        UntrustedContent(source_kind="run_activity", source_ref=source_ref, content=content)
    )


def _clip(value: str, limit: int, *, collapse: bool = True) -> str:
    # Collapsing whitespace stops untrusted text from forging digest lines or headings.
    text = " ".join(value.split()) if collapse else value.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n[digest truncated]\n"
    head = limit // 3
    return text[:head] + marker + text[-(limit - head - len(marker)) :]
