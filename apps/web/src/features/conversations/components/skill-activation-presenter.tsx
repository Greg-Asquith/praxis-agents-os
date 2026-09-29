// apps/web/src/features/conversations/components/skill-activation-presenter.tsx

import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import {
  internalSkillLabelFromCapabilityArgs,
  LOAD_CAPABILITY_TOOL_NAME,
  LOAD_SKILL_TOOL_NAME,
  loadedSkillNameFromArgs,
} from "@/features/conversations/skills/skill-activation"
import type { ToolRowPresenter } from "@/integrations/contract"

export const skillActivationPresenter: ToolRowPresenter = {
  key: "skill-activation",
  matches: (activity) =>
    (activity.name === LOAD_SKILL_TOOL_NAME && loadedSkillNameFromArgs(activity.args) !== null) ||
    ((activity.toolKind === "capability-load" || activity.name === LOAD_CAPABILITY_TOOL_NAME) &&
      internalSkillLabelFromCapabilityArgs(activity.args) !== null),
  render: ({ activity }) => <SkillActivationRow activity={activity} />,
}
