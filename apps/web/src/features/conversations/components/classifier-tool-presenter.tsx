// apps/web/src/features/conversations/components/classifier-tool-presenter.tsx

import { ClassifierToolRow } from "@/features/conversations/components/classifier-tool-row"
import {
  CLASSIFY_TOOL_NAME,
  classifierResult,
  isClassifierToolName,
} from "@/features/conversations/native-tools/classifier-tool"
import type { ToolRowPresenter } from "@/integrations/contract"

export const classifierToolPresenter: ToolRowPresenter = {
  key: "classifier",
  matches: (activity) =>
    isClassifierToolName(activity.name) &&
    (activity.status === "running" ||
      activity.status === "failed" ||
      activity.status === "denied" ||
      activity.status === "unknown" ||
      (activity.status === "completed" &&
        classifierResult(activity.args, activity.result) !== null)),
  render: ({ activity, defaultOpen, label }) => (
    <ClassifierToolRow
      activity={activity}
      defaultOpen={defaultOpen}
      label={
        activity.name === CLASSIFY_TOOL_NAME
          ? "Classify"
          : label && label !== activity.name
            ? label
            : "Classifier"
      }
    />
  ),
}
