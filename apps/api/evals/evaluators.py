# apps/api/evals/evaluators.py

"""Shared programmatic evaluators for agent-behavior datasets."""

import ast
import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai import Tool
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG

FIXTURE_ROOT = Path(__file__).parents[1] / "tests"


@dataclass(frozen=True)
class EvalOutput:
    text: str
    called_tools: tuple[str, ...] = ()
    tool_arguments: tuple[str, ...] = ()


@dataclass
class ExpectedTools(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        expected = set((ctx.metadata or {}).get("expected_tools", []))
        return expected.issubset(ctx.output.called_tools)


@dataclass
class ForbiddenTools(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        forbidden = set((ctx.metadata or {}).get("forbidden_tools", []))
        return forbidden.isdisjoint(ctx.output.called_tools)


@dataclass
class RequiredText(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        required = (ctx.metadata or {}).get("required_text", [])
        lowered = ctx.output.text.lower()
        return all(str(value).lower() in lowered for value in required)


@dataclass
class ForbiddenArgumentText(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        forbidden = (ctx.metadata or {}).get("forbidden_argument_text", [])
        arguments = "\n".join(ctx.output.tool_arguments).lower()
        return all(str(value).lower() not in arguments for value in forbidden)


@dataclass
class OutputFormat(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        expected = (ctx.metadata or {}).get("output_format")
        if not expected:
            return True
        if expected.get("kind") == "json_object":
            try:
                parsed = json.loads(ctx.output.text)
            except (TypeError, json.JSONDecodeError):
                return False
            return parsed == expected.get("value")
        if expected.get("kind") == "markdown_bullets":
            lines = [line.strip() for line in ctx.output.text.splitlines() if line.strip()]
            return len(lines) == expected.get("count") and all(
                line.startswith("- ") for line in lines
            )
        return False


@dataclass
class AcceptedToolCall(Evaluator[dict, EvalOutput, dict]):
    """Checks the first call uses an accepted tool, directly or in a script, with valid arguments."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        metadata = ctx.metadata or {}
        accepted = metadata.get("accepted_tools")
        if not accepted:
            return EvaluationReason(value=True)
        if not ctx.output.called_tools:
            return EvaluationReason(value=False, reason="no tool was called")
        name, arguments = ctx.output.called_tools[0], ctx.output.tool_arguments[0]
        if name == "run_code":
            code = _script_code(arguments)
            if code is None:
                return EvaluationReason(value=False, reason="run_code arguments aren't JSON")
            called, errors = workflow_calls(code, code_eligible_tools())
            if called.isdisjoint(accepted):
                errors = (*errors, f"the script calls none of {sorted(accepted)}")
        elif name in accepted:
            errors = _direct_argument_errors(name, arguments)
        else:
            errors = (f"first call was {name}",)
        missing = [
            text
            for text in metadata.get("required_argument_text", [])
            if str(text).lower() not in arguments.lower()
        ]
        if missing:
            errors = (*errors, f"arguments lack {missing}")
        return EvaluationReason(value=not errors, reason="; ".join(errors) or None)


@dataclass
class ExpectedClips(Evaluator[dict, EvalOutput, dict]):
    """Checks the first cut_video_clips call cuts exactly the expected clips, in any order."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        expected = (ctx.metadata or {}).get("expected_clips")
        if not expected:
            return EvaluationReason(value=True)
        if "cut_video_clips" not in ctx.output.called_tools:
            return EvaluationReason(value=False, reason="cut_video_clips was not called")
        arguments = ctx.output.tool_arguments[ctx.output.called_tools.index("cut_video_clips")]
        try:
            clips = json.loads(arguments)["clips"]
            cut = sorted(
                [[segment.get("start_ms"), segment.get("end_ms")] for segment in clip["segments"]]
                for clip in clips
            )
        except (TypeError, KeyError, AttributeError, json.JSONDecodeError):
            return EvaluationReason(value=False, reason="cut_video_clips arguments aren't clips")
        if cut != sorted(expected):
            return EvaluationReason(value=False, reason=f"cut {cut}, expected {sorted(expected)}")
        return EvaluationReason(value=True)


@dataclass
class ExpectedForecast(Evaluator[dict, EvalOutput, dict]):
    """Checks the first call forecasts once, directly or in a script, with the expected
    settings, and that any literal history is the fixture's history unchanged."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        expected = (ctx.metadata or {}).get("expected_forecast")
        if not expected:
            return EvaluationReason(value=True)
        if not ctx.output.called_tools:
            return EvaluationReason(value=False, reason="no tool was called")
        arguments, source, errors = _forecast_arguments(
            ctx.output.called_tools[0], ctx.output.tool_arguments[0]
        )
        if arguments is not None:
            errors = _forecast_argument_errors(arguments, source, expected)
        return EvaluationReason(value=not errors, reason="; ".join(errors) or None)


@dataclass
class WorkflowArguments(Evaluator[dict, EvalOutput, dict]):
    """Checks that a workflow calls the expected tools with valid keyword arguments."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        expected = (ctx.metadata or {}).get("workflow_tools")
        if not expected:
            return EvaluationReason(value=True)
        if "run_code" not in ctx.output.called_tools:
            return EvaluationReason(value=False, reason="run_code was not called")
        arguments = ctx.output.tool_arguments[ctx.output.called_tools.index("run_code")]
        code = _script_code(arguments)
        if code is None:
            return EvaluationReason(value=False, reason="run_code arguments aren't JSON")
        errors = workflow_argument_errors(code, code_eligible_tools(), expected)
        return EvaluationReason(value=not errors, reason="; ".join(errors) or None)


def _forecast_arguments(name: str, arguments: str) -> tuple[dict | None, str, tuple[str, ...]]:
    """Returns a direct call's arguments, or a script's literal ones and its source."""
    if name == "forecast_series":
        errors = _direct_argument_errors(name, arguments)
        return (None, "", errors) if errors else (json.loads(arguments), "", ())
    if name != "run_code":
        return None, "", (f"first call was {name}",)
    code = _script_code(arguments)
    if code is None:
        return None, "", ("run_code arguments aren't JSON",)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return None, "", (f"syntax error: {exc.msg}",)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "forecast_series"
    ]
    if len(calls) != 1:
        return None, "", (f"the script calls forecast_series {len(calls)} times",)
    # A keyword that names a variable takes the literal assigned to it, if any.
    assigned = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    literal: dict = {}
    for keyword in calls[0].keywords:
        value = keyword.value
        if isinstance(value, ast.Name):
            value = assigned.get(value.id, value)
        try:
            literal[keyword.arg] = ast.literal_eval(value)
        except ValueError:
            # Values computed at run time are only checked against the source.
            continue
    return literal, code, ()


def _forecast_argument_errors(arguments: dict, source: str, expected: Mapping) -> tuple[str, ...]:
    errors = []
    for key in ("frequency", "horizon"):
        if key in arguments:
            found = arguments[key] == expected[key]
        else:
            found = repr(expected[key]) in source or json.dumps(expected[key]) in source
        if not found:
            errors.append(f"{key} isn't {expected[key]!r}")
    for region in expected["holiday_regions"]:
        if "holiday_regions" in arguments:
            found = region in (arguments["holiday_regions"] or [])
        else:
            found = repr(region) in source or json.dumps(region) in source
        if not found:
            errors.append(f"holiday_regions lacks {region!r}")
    start = arguments.get("start")
    if start is not None and not str(start).startswith(expected["start"]):
        errors.append(f"start is {start!r}, expected {expected['start']!r}")
    values = arguments.get("values")
    if values is not None:
        path = (FIXTURE_ROOT / expected["history_fixture_path"]).resolve()
        with path.open(encoding="utf-8") as handle:
            history = [float(row[expected["history_column"]]) for row in csv.DictReader(handle)]
        if [None if value is None else float(value) for value in values] != history:
            errors.append(f"values aren't the {len(history)}-period history")
    return tuple(errors)


def _script_code(arguments: str) -> str | None:
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return None
    return str(parsed.get("code", "")) if isinstance(parsed, dict) else None


def code_eligible_tools() -> dict[str, Tool]:
    """Return the catalogue's code-eligible tools by name."""
    return {
        definition.name: definition.to_pydantic_tool()
        for definition in RUNTIME_TOOL_CATALOG.values()
        if definition.code_eligible
    }


def workflow_argument_errors(
    code: str,
    tools: Mapping[str, Tool],
    expected_tools: list[str],
) -> tuple[str, ...]:
    """Check each tool call in workflow code against the tool's argument validator."""
    called, errors = workflow_calls(code, tools)
    return (*errors, *(f"{name}: not called" for name in expected_tools if name not in called))


def workflow_calls(code: str, tools: Mapping[str, Tool]) -> tuple[set[str], tuple[str, ...]]:
    """Return the tools workflow code calls and the argument errors in those calls."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return set(), (f"syntax error: {exc.msg}",)
    errors: list[str] = []
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        tool = tools.get(node.func.id)
        if tool is None:
            continue
        called.add(tool.name)
        error = _call_argument_error(node, tool)
        if error is not None:
            errors.append(f"{tool.name}: {error}")
    return called, tuple(errors)


def _direct_argument_errors(name: str, arguments: str) -> tuple[str, ...]:
    try:
        RUNTIME_TOOL_CATALOG[name].to_pydantic_tool().function_schema.validator.validate_json(
            arguments
        )
    except ValidationError as exc:
        error = exc.errors(include_url=False)[0]
        return (f"{name}: {'.'.join(map(str, error['loc']))}: {error['msg']}",)
    return ()


def _call_argument_error(node: ast.Call, tool: Tool) -> str | None:
    if node.args:
        return "positional arguments"
    if any(keyword.arg is None for keyword in node.keywords):
        return None
    schema = tool.function_schema.json_schema
    names = {keyword.arg for keyword in node.keywords}
    unknown = sorted(names - set(schema.get("properties", {})))
    missing = sorted(set(schema.get("required", [])) - names)
    if unknown or missing:
        return f"unknown {unknown}, missing {missing}"
    try:
        literal_args = {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords}
    except ValueError:
        # Values computed at run time are only checked by name.
        return None
    try:
        tool.function_schema.validator.validate_python(literal_args)
    except ValidationError as exc:
        return f"invalid arguments: {exc.errors(include_url=False)[0]['msg']}"
    return None
