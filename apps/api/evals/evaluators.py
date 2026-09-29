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
        tools = {
            definition.name: definition.to_pydantic_tool()
            for definition in RUNTIME_TOOL_CATALOG.values()
            if definition.code_eligible
        }
        errors = workflow_argument_errors(code, tools, expected)
        return EvaluationReason(value=not errors, reason="; ".join(errors) or None)


def workflow_argument_errors(
    code: str,
    tools: Mapping[str, Tool],
    expected_tools: list[str],
) -> tuple[str, ...]:
    """Check each tool call in workflow code against the tool's argument validator."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return (f"syntax error: {exc.msg}",)
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
    errors.extend(f"{name}: not called" for name in expected_tools if name not in called)
    return tuple(errors)


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
