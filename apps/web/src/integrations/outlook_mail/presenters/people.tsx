// apps/web/src/integrations/outlook_mail/presenters/people.tsx

import type { DataColumn } from "@/components/ui/data-table"
import { OutlookRecordTable } from "@/integrations/outlook_mail/components/record-table"
import { peopleRows } from "@/integrations/outlook_mail/lib/record-lists"
import { outlookPeopleDetails } from "@/integrations/outlook_mail/lib/tool-details"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

const COLUMNS: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "address", label: "Email", kind: "text", width: "auto" },
  { key: "job_title", label: "Job title", kind: "text" },
  { key: "department", label: "Department", kind: "text" },
]

export const outlookMailPeoplePresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "Search Outlook People results",
  details: outlookPeopleDetails,
  emptyLabel: "No mailboxes returned a result.",
  heading: "Search Outlook People",
  parseResult: peopleRows,
  progressLabel: "Searching people…",
  render: (rows) => (
    <OutlookRecordTable
      columns={COLUMNS}
      emptyLabel="No people found."
      exportFilename="outlook-people.csv"
      noun="Person"
      nounPlural="People"
      rows={rows}
    />
  ),
  tool: "outlook_mail_search_people",
})
