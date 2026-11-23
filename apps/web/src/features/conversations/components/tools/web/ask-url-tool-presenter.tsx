// apps/web/src/features/conversations/components/tools/web/ask-url-tool-presenter.tsx

import {
  ASK_URL_TOOL_NAME,
  askUrlResult,
  askUrlUrl,
} from "@/features/conversations/components/tools/web/ask-url-result"
import { AskUrlToolRow } from "@/features/conversations/components/tools/web/ask-url-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const askUrlToolPresenter: ToolRowPresenter = {
  key: "ask-url",
  matches: (activity) =>
    activity.name === ASK_URL_TOOL_NAME &&
    (activity.status === "running"
      ? askUrlUrl(activity.args) !== null
      : activity.status === "completed" && askUrlResult(activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <AskUrlToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
