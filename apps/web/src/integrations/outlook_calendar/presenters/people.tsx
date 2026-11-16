// apps/web/src/integrations/outlook_calendar/presenters/people.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { peopleRows } from "@/integrations/outlook_calendar/lib/events"
import { peopleDetails } from "@/integrations/outlook_calendar/lib/tool-details"
import { outlookCalendarProvider } from "@/integrations/outlook_calendar/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

const COLUMNS: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "address", label: "Email", kind: "text", width: "auto" },
  { key: "job_title", label: "Job Title", kind: "text" },
  { key: "department", label: "Department", kind: "text" },
]

export const outlookCalendarPeoplePresenter = defineIntegrationReadPresenter(
  outlookCalendarProvider,
  {
    ariaLabel: "Search Outlook People results",
    details: peopleDetails,
    emptyLabel: "No calendars returned a result.",
    heading: "Search Outlook People",
    parseResult: peopleRows,
    progressLabel: "Searching people…",
    render: (rows) =>
      rows.length === 0 ? (
        <EmptyResult>No people found.</EmptyResult>
      ) : (
        <DataTable
          columns={COLUMNS}
          exportFilename="outlook-people.csv"
          pageSize={25}
          rowNoun={["Person", "People"]}
          rows={rows}
        />
      ),
    tool: "outlook_calendar_search_people",
  }
)
