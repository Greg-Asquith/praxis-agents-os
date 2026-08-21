// apps/web/src/features/conversations/components/skill-activation-presenter.tsx

import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import {
  LOAD_CAPABILITY_TOOL_NAME,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skills/skill-activation"
import type { ToolRowPresenter } from "@/integrations/contract"

export const skillActivationPresenter: ToolRowPresenter = {
  key: "skill-activation",
  matches: (activity) =>
    (activity.toolKind === "capability-load" || activity.name === LOAD_CAPABILITY_TOOL_NAME) &&
    skillIdFromCapabilityArgs(activity.args) !== null,
  render: ({ activity }) => <SkillActivationRow activity={activity} />,
}
