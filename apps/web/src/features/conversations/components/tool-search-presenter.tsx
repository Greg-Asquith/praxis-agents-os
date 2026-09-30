// apps/web/src/features/conversations/components/tool-search-presenter.tsx

import { ToolSearchRow } from "@/features/conversations/components/tool-search-row"
import { isToolSearchName } from "@/features/conversations/native-tools/tool-search"
import type { ToolRowPresenter } from "@/integrations/contract"

export const toolSearchPresenter: ToolRowPresenter = {
  key: "tool-search",
  matches: (activity) => isToolSearchName(activity.name),
  render: ({ activity, defaultOpen }) => (
    <ToolSearchRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
