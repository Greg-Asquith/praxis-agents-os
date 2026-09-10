// apps/web/src/integrations/google_search_console/presenters/inspection.tsx

import { InspectionResults } from "@/integrations/google_search_console/components/inspection-results"
import { parseInspectionData } from "@/integrations/google_search_console/lib/inspection-model"
import { googleSearchConsoleProvider } from "@/integrations/google_search_console/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleSearchConsoleInspectionPresenter = defineIntegrationReadPresenter(
  googleSearchConsoleProvider,
  {
    ariaLabel: "Search Console URL inspection results",
    emptyLabel: "No Search Console sites were inspected.",
    heading: "Inspect Search Console URLs",
    parseResult: parseInspectionData,
    progressLabel: "Inspecting Search Console URLs…",
    render: (inspections) => <InspectionResults inspections={inspections} />,
    tool: "google_search_console_inspect_url",
  }
)
