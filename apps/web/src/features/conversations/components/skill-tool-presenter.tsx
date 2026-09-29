// apps/web/src/features/conversations/components/skill-tool-presenter.tsx

import { SkillToolRow } from "@/features/conversations/components/skill-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  CREATE_SKILL_TOOL_NAME,
  SEARCH_SKILLS_TOOL_NAME,
  UPDATE_SKILL_TOOL_NAME,
  loadSkillResult,
  savedSkillResult,
  searchSkillsResult,
} from "@/features/conversations/native-tools/skill-tools"
import { LOAD_SKILL_TOOL_NAME } from "@/features/conversations/skills/skill-activation"
import type { ToolRowPresenter } from "@/integrations/contract"

export const skillToolPresenter: ToolRowPresenter = {
  key: "skill-tools",
  matches: skillToolRowMatches,
  render: ({ activity, defaultOpen }) => (
    <SkillToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}

// Skill writes keep the declarative approval card until they finish.
function skillToolRowMatches(activity: ToolActivity) {
  if (activity.name === CREATE_SKILL_TOOL_NAME || activity.name === UPDATE_SKILL_TOOL_NAME) {
    return activity.status === "completed" && savedSkillResult(activity.result) !== null
  }
  if (activity.name !== SEARCH_SKILLS_TOOL_NAME && activity.name !== LOAD_SKILL_TOOL_NAME) {
    return false
  }
  if (activity.status !== "completed") {
    return true
  }
  return activity.name === SEARCH_SKILLS_TOOL_NAME
    ? searchSkillsResult(activity.result) !== null
    : loadSkillResult(activity.result) !== null
}
