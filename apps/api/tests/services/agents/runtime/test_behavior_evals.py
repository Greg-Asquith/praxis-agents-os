# apps/api/tests/services/agents/runtime/test_behavior_evals.py

"""Deterministic checks for the opt-in live-model evaluation harness."""

import json
from types import SimpleNamespace

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_evals.evaluators import LLMJudge
from pydantic_evals.evaluators.llm_as_a_judge import GradingOutput

from evals.evaluators import (
    AcceptedToolCall,
    EvalOutput,
    OutputFormat,
    workflow_argument_errors,
)
from evals.run import _load_dataset
from services.agents.runtime.tools.contract import RuntimeToolDefinition


def _passing_judge(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    grade = GradingOutput(reason="The response satisfies the rubric.", pass_=True, score=1)
    args = grade.model_dump(by_alias=True)
    if info.output_tools:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])
    return ModelResponse(parts=[TextPart(grade.model_dump_json(by_alias=True))])


async def test_dataset_uses_case_judges_and_programmatic_output_formats() -> None:
    judge_model = FunctionModel(_passing_judge, model_name="eval-judge-probe")
    dataset = _load_dataset(judge_model)
    cases = {case.name: case for case in dataset.cases}

    assert len(cases) == 26
    assert not any(isinstance(item, LLMJudge) for item in cases["list_files_selection"].evaluators)
    assert not any(isinstance(item, LLMJudge) for item in cases["json_format"].evaluators)
    judges = [item for item in cases["identity_name"].evaluators if isinstance(item, LLMJudge)]
    assert len(judges) == 3
    assert all(judge.model is judge_model for judge in judges)
    assert [judge.assertion["evaluation_name"] for judge in judges] == [
        "instruction_adherence",
        "safe_and_honest",
        "response_quality",
    ]
    gmail_case = cases["injection_gmail_message_reports_embedded_instructions"]
    assert gmail_case.inputs["channel_fixture"]["source_kind"] == "gmail_message"
    for kind in ("outlook_message", "outlook_person"):
        case = cases[f"injection_{kind}_reports_embedded_instructions"]
        assert case.inputs["channel_fixture"]["source_kind"] == kind
        assert case.inputs["channel_fixture"]["fixture_path"] == (
            "fixtures/prompt_injection/hostile_email_body.txt"
        )
    web_fetch_case = cases["injection_web_fetch_reports_embedded_instructions"]
    assert web_fetch_case.inputs["channel_fixture"]["source_kind"] == "web_fetch"
    assert "fetch_url" in web_fetch_case.metadata["forbidden_tools"]
    code_mode_case = cases["injection_code_mode_hostile_intermediate_blocks_external_action"]
    assert code_mode_case.inputs["channel_fixture"]["source_kind"] == "code_mode_workflow"
    assert "write_file" in code_mode_case.metadata["forbidden_tools"]
    assert "exfiltrate-now" in code_mode_case.metadata["forbidden_argument_text"]
    kb_search_case = cases["injection_scaffold_kb_ignore_instructions"]
    kb_read_case = cases["injection_scaffold_kb_read_document"]
    summary_case = cases["injection_history_summary_does_not_launder"]
    assert kb_search_case.inputs["channel_fixture"]["source_kind"] == "kb"
    assert "prompt_injection_basic.md" in kb_search_case.inputs["channel_fixture"]["fixture_path"]
    assert kb_read_case.inputs["channel_fixture"]["source_ref"].startswith("document:")
    artifact_case = cases["injection_platform_artifact_reports_embedded_instructions"]
    assert artifact_case.inputs["channel_fixture"]["source_kind"] == "artifact"
    assert "update_artifact" in artifact_case.metadata["forbidden_tools"]
    assert any(isinstance(item, LLMJudge) for item in artifact_case.evaluators)
    assert summary_case.inputs["history_summary_fixture_path"].endswith(
        "hostile_conversation_span.txt"
    )

    judgment = await judges[0].evaluate(
        SimpleNamespace(inputs={"prompt": "Who are you?"}, output=EvalOutput("Praxis"))
    )
    assert judgment["instruction_adherence"].value is True

    evaluator = OutputFormat()
    json_context = SimpleNamespace(
        output=EvalOutput('{"status":"ready"}'),
        metadata={"output_format": {"kind": "json_object", "value": {"status": "ready"}}},
    )
    bullet_context = SimpleNamespace(
        output=EvalOutput("- one\n- two\n- three"),
        metadata={"output_format": {"kind": "markdown_bullets", "count": 3}},
    )
    assert evaluator.evaluate(json_context)
    assert evaluator.evaluate(bullet_context)


def test_workflow_argument_errors_flag_guessed_and_malformed_arguments() -> None:
    def run_report(date_ranges: list[dict[str, str]], limit: int | None = None) -> str:
        return ""

    tool = RuntimeToolDefinition(
        name="run_report",
        function=run_report,
        description="Run a report.",
        code_eligible=True,
    ).to_pydantic_tool()
    tools = {"run_report": tool}

    assert (
        workflow_argument_errors(
            "for start in starts:\n    await run_report(date_ranges=[{'start': start}])",
            tools,
            ["run_report"],
        )
        == ()
    )
    assert workflow_argument_errors(
        "await run_report(start_date='2026-09-01')", tools, ["run_report"]
    ) == ("run_report: unknown ['start_date'], missing ['date_ranges']",)
    assert workflow_argument_errors(
        "await run_report(date_ranges='yesterday')", tools, ["run_report"]
    ) == ("run_report: invalid arguments: Input should be a valid list",)


def test_accepted_tool_call_validates_direct_and_workflow_document_edits() -> None:
    reference = {"entity_id": "00000000-0000-0000-0000-000000000001", "label": "Sales.xlsx"}
    edit = {
        "file_id": reference,
        "base_revision_id": "00000000-0000-0000-0000-000000000002",
        "operations": [
            {"op": "set_cells", "sheet": "Sales", "anchor": "B8", "values": [["=SUM(B2:B7)"]]}
        ],
    }
    metadata = {"accepted_tools": ["edit_workbook"], "required_argument_text": ["=SUM("]}

    def verdict(tool_name: str, arguments: dict) -> bool:
        output = EvalOutput("", (tool_name,), (json.dumps(arguments),))
        context = SimpleNamespace(output=output, metadata=metadata)
        return AcceptedToolCall().evaluate(context).value

    assert verdict("edit_workbook", edit)
    assert verdict("run_workflow", {"code": f"await edit_workbook(**{edit!r})"})
    # A cell anchor that isn't A1 notation fails the operation union, not just the name check.
    assert not verdict(
        "edit_workbook",
        {**edit, "operations": [{**edit["operations"][0], "anchor": "row 8"}]},
    )
    assert not verdict("run_code", {"task": "Add =SUM( totals"})
