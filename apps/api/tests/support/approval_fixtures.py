"""Restores synthetic historical approvals under fresh scenario identities."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.create import create_agent_run
from tests.factories import build_conversation
from tests.support.scenario import add_scenario_delegate, build_scenario_agent

FIXTURES = Path(__file__).parents[1] / "fixtures" / "approvals_v1"


async def restore_approval_fixture(factory, name):
    """Rebinds database references without changing saved interpreter bytes or consent."""
    records = json.loads((FIXTURES / f"{name}.json").read_text())
    original_root = next(row for row in records if row["parent_run_id"] is None)
    context = await build_scenario_agent(
        factory,
        tool_names=["write_file"] if name == "staged" else ["scenario_release_write"],
        code_mode_enabled="code_mode_state" in original_root["metadata_json"],
        trigger="scheduled",
    )
    restored = {}
    replacements = {}
    for record in sorted(records, key=lambda row: row["parent_run_id"] is not None):
        if record is original_root:
            run_id = context.run_id
        else:
            agent = await add_scenario_delegate(
                factory, context, tool_names=["scenario_release_write"]
            )
            async with factory() as db:
                from models.agent import Agent

                (await db.get(Agent, agent.id)).code_mode_enabled = True
                conversation = build_conversation(
                    user=await db.get(User, context.user_id),
                    workspace=await db.get(Workspace, context.workspace_id),
                    active_agent_id=agent.id,
                )
                db.add(conversation)
                await db.flush()
                run = await create_agent_run(
                    db,
                    conversation_id=conversation.id,
                    agent_id=agent.id,
                    workspace_id=context.workspace_id,
                    user_id=context.user_id,
                    trigger="delegated",
                    parent_run_id=context.run_id,
                    delegation_depth=1,
                )
                run_id = run.id
                await db.commit()
        async with factory() as db:
            run = await db.get(AgentRun, run_id)
            for key in ("id", "conversation_id", "agent_id", "workspace_id", "user_id"):
                replacements[record[key]] = str(getattr(run, key))
            restored[record["id"]] = run_id
    async with factory() as db:
        for record in records:
            run = await db.get(AgentRun, restored[record["id"]])
            raw = json.dumps(record["metadata_json"])
            for previous, replacement in replacements.items():
                raw = raw.replace(previous, replacement)
            run.metadata_json = json.loads(raw)
            run.usage_json = record["usage_json"]
            run.status = record["status"]
            run.started_at = datetime.now(UTC)
            run.owner_instance_id = str(uuid4())
            run.lease_expires_at = None
        await db.commit()
    return context
