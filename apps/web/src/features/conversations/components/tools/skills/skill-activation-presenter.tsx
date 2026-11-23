// apps/web/src/features/conversations/components/tools/skills/skill-activation-presenter.tsx

import { SkillActivationRow } from "@/features/conversations/components/tools/skills/skill-activation-row"
import {
  internalSkillLabelFromCapabilityArgs,
  LOAD_CAPABILITY_TOOL_NAME,
} from "@/features/conversations/skills/skill-activation"
import type { ToolRowPresenter } from "@/integrations/contract"

export const skillActivationPresenter: ToolRowPresenter = {
  key: "skill-activation",
  matches: (activity) =>
    (activity.toolKind === "capability-load" || activity.name === LOAD_CAPABILITY_TOOL_NAME) &&
    internalSkillLabelFromCapabilityArgs(activity.args) !== null,
  render: ({ activity }) => <SkillActivationRow activity={activity} />,
}
