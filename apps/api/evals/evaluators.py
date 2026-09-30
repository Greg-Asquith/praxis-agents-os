# apps/api/evals/evaluators.py

"""Shared programmatic evaluators for agent-behavior datasets."""

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_ai import Tool
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG


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
    """Checks that the first call uses an accepted tool, directly or in a workflow, with valid arguments."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        metadata = ctx.metadata or {}
        accepted = metadata.get("accepted_tools")
        if not accepted:
            return EvaluationReason(value=True)
        if not ctx.output.called_tools:
            return EvaluationReason(value=False, reason="no tool was called")
        name, arguments = ctx.output.called_tools[0], ctx.output.tool_arguments[0]
        if name == "run_workflow":
            code = str(json.loads(arguments).get("code", ""))
            called, errors = workflow_calls(code, code_eligible_tools())
            if called.isdisjoint(accepted):
                errors = (*errors, f"the workflow calls none of {sorted(accepted)}")
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
class WorkflowArguments(Evaluator[dict, EvalOutput, dict]):
    """Checks that a workflow calls the expected tools with valid keyword arguments."""

    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> EvaluationReason:
        expected = (ctx.metadata or {}).get("workflow_tools")
        if not expected:
            return EvaluationReason(value=True)
        if "run_workflow" not in ctx.output.called_tools:
            return EvaluationReason(value=False, reason="run_workflow was not called")
        arguments = ctx.output.tool_arguments[ctx.output.called_tools.index("run_workflow")]
        code = str(json.loads(arguments).get("code", ""))
        errors = workflow_argument_errors(code, code_eligible_tools(), expected)
        return EvaluationReason(value=not errors, reason="; ".join(errors) or None)


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
