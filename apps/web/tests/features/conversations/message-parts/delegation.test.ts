// apps/web/tests/features/conversations/message-parts/delegation.test.ts

import { describe, expect, it } from "vitest"

import {
  delegationDetailsForPendingApproval,
  delegationDetailsForToolActivity,
  mergeDelegationDetails,
} from "@/features/conversations/message-parts/delegation"

const AGENT_ID = "33333333-3333-4333-8333-333333333333"

describe("delegationDetailsForToolActivity", () => {
  it("names the target agent from the structured reference before the result arrives", () => {
    const details = delegationDetailsForToolActivity("delegate_to_agent", {
      agent_id: {
        version: 1,
        entity_kind: "agent",
        entity_id: AGENT_ID,
        label: "Gmail Agent",
        description: null,
        scope_label: null,
      },
      task: "Summarise the inbox",
    })

    expect(details?.status).toBe("running")
    expect(details?.agentId).toBe(AGENT_ID)
    expect(details?.agentName).toBe("Gmail Agent")
    expect(details?.taskPreview).toBe("Summarise the inbox")
  })

  it("accepts a plain id and prefers the result's name once it exists", () => {
    const fromString = delegationDetailsForToolActivity("delegate_to_agent", {
      agent_id: AGENT_ID,
      task: "Summarise the inbox",
    })
    const withResult = delegationDetailsForToolActivity(
      "delegate_to_agent",
      JSON.stringify({
        agent_id: { entity_kind: "agent", entity_id: AGENT_ID, label: "Old name" },
        task: "Summarise the inbox",
      }),
      { status: "completed", agent_id: AGENT_ID, agent_name: "Gmail Agent", output: "Done." }
    )

    expect(fromString?.agentId).toBe(AGENT_ID)
    expect(fromString?.agentName).toBeNull()
    expect(withResult?.status).toBe("completed")
    expect(withResult?.agentName).toBe("Gmail Agent")
  })

  it("names a sub-agent by its role and never by the parent's agent id", () => {
    const details = delegationDetailsForToolActivity(
      "run_subagent",
      { role: "Search term researcher", instructions: "Research.", task: "Find terms" },
      { status: "completed", agent_id: AGENT_ID, agent_name: "Search term researcher" }
    )

    expect(details?.agentId).toBeNull()
    expect(details?.agentName).toBe("Search term researcher")
    expect(details?.taskPreview).toBe("Find terms")

    const pending = mergeDelegationDetails(
      details,
      delegationDetailsForPendingApproval({
        parent_tool_call_id: "spawn-1",
        parent_tool_name: "run_subagent",
        child_agent_id: AGENT_ID,
        child_agent_name: "Search term researcher",
        child_conversation_id: "child-conversation",
        child_run_id: "child-run",
        pending_approval_count: 1,
      })
    )

    expect(pending?.status).toBe("awaiting_approval")
    expect(pending?.agentId).toBeNull()
    expect(pending?.conversationId).toBe("child-conversation")
  })

  it("ignores references of another kind and other tools", () => {
    const otherKind = delegationDetailsForToolActivity("delegate_to_agent", {
      agent_id: { entity_kind: "memory", entity_id: AGENT_ID, label: "Note" },
      task: "x",
    })

    expect(otherKind?.agentId).toBeNull()
    expect(otherKind?.agentName).toBeNull()
    expect(delegationDetailsForToolActivity("send_email", { agent_id: AGENT_ID })).toBeUndefined()
  })
})
