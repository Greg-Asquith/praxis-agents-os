// apps/web/src/integrations/google_search_console/presenters/inspection.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { InspectionResults } from "@/integrations/google_search_console/components/inspection-results"
import { GoogleSearchConsoleToolHeading } from "@/integrations/google_search_console/components/tool-heading"
import { parseInspectionData } from "@/integrations/google_search_console/lib/inspection-model"
import type { ToolRowPresenter } from "@/integrations/contract"

export const inspectionPresenter: ToolRowPresenter = {
  key: "google-search-console-inspect-url",
  matches: (activity) => activity.name === "google_search_console_inspect_url",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleSearchConsoleToolHeading>
              Inspect Search Console URLs
            </GoogleSearchConsoleToolHeading>
          }
          label="Inspecting Search Console URLs…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseInspectionData)
    if (!fanOut) return null
    return (
      <div aria-label="Search Console URL inspection results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Site"
          defaultOpen={defaultOpen}
          emptyLabel="No Search Console sites were inspected."
          entries={fanOut.entries}
          externalLabel="Site URL"
          heading={
            <GoogleSearchConsoleToolHeading>
              Inspect Search Console URLs
            </GoogleSearchConsoleToolHeading>
          }
        >
          {(_entry, index) => {
            const inspections = fanOut.data[index]
            return inspections ? <InspectionResults inspections={inspections} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}
