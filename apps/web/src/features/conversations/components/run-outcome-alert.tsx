// apps/web/src/features/conversations/components/run-outcome-alert.tsx

import { Link } from "@tanstack/react-router"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import type { RunInterruptionOutcome } from "@/features/conversations/run-error-copy"

export function RunOutcomeAlert({ outcome }: { outcome: RunInterruptionOutcome }) {
  const toolLabel = useToolLabels()
  const paused = outcome.kind === "budget_exhausted"
  return (
    <div className="w-full px-1 py-2">
      <Alert variant={paused ? "default" : "destructive"}>
        <AlertTitle>{outcome.title}</AlertTitle>
        <AlertDescription>
          <p>{outcome.message}</p>
          {outcome.completedActions.length > 0 ? (
            <details className="mt-2" open={!paused}>
              <summary className="cursor-pointer font-medium">
                {paused ? "What It Did So Far" : "Completed Actions"}
              </summary>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5">
                {groupedActions(outcome.completedActions, toolLabel).map(([label, count]) => (
                  <li key={label}>{count > 1 ? `${label} ×${String(count)}` : label}</li>
                ))}
              </ul>
            </details>
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

// Repeated calls collapse into one line with a count, in first-use order.
function groupedActions(
  actions: readonly { toolName: string }[],
  toolLabel: (name: string) => string
): [string, number][] {
  const counts = new Map<string, number>()
  for (const action of actions) {
    const label = toolLabel(action.toolName)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return [...counts]
}
