// apps/web/src/features/conversations/components/todo-list-presenter.tsx

import { TodoListRow } from "@/features/conversations/components/todo-list-row"
import {
  READ_TODOS_TOOL_NAME,
  WRITE_TODOS_TOOL_NAME,
  todoItemsFromActivity,
} from "@/features/conversations/native-tools/todo-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

export const todoToolPresenters: ToolRowPresenter[] = [
  {
    key: "todo-plan",
    matches: (activity) =>
      activity.name === WRITE_TODOS_TOOL_NAME && todoItemsFromActivity(activity) !== null,
    render: ({ activity }) => <TodoListRow activity={activity} />,
  },
  {
    key: "todo-lookup",
    matches: (activity) =>
      activity.name === READ_TODOS_TOOL_NAME &&
      (activity.status !== "completed" || todoItemsFromActivity(activity) !== null),
    render: ({ activity }) => <TodoListRow activity={activity} />,
  },
]
