// apps/web/src/features/conversations/components/run-outcome-alert.tsx

import { Link } from "@tanstack/react-router"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import type { RunInterruptionOutcome } from "@/features/conversations/run-error-copy"

export function RunOutcomeAlert({ outcome }: { outcome: RunInterruptionOutcome }) {
  const toolLabel = useToolLabels()
  return (
    <div className="w-full px-1 py-2">
      <Alert variant="destructive">
        <AlertTitle>{outcome.title}</AlertTitle>
        <AlertDescription>
          <p>{outcome.message}</p>
          {outcome.completedActions.length > 0 ? (
            <div className="mt-2">
              <p className="font-medium">Completed Actions</p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5">
                {outcome.completedActions.map((action) => (
                  <li key={action.id}>{toolLabel(action.toolName)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {outcome.uncertainActions?.length ? (
            <div className="mt-2">
              <p className="font-medium">Actions with an uncertain result</p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5">
                {outcome.uncertainActions.map((action) => (
                  <li key={action.id}>{toolLabel(action.toolName)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {outcome.actionsTruncated ? (
            <p className="mt-1">More actions are recorded in the run transcripts.</p>
          ) : null}
          {outcome.childConversations?.map((childId, index) => (
            <Link
              key={childId}
              to="/conversations/$conversationId"
              params={{ conversationId: childId }}
              className="mt-1 block underline"
            >
              Review specialist conversation {index + 1}
            </Link>
          ))}
        </AlertDescription>
      </Alert>
    </div>
  )
}
