// apps/web/src/integrations/outlook_mail/presenters/people.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { DataColumn } from "@/components/ui/data-table"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookSkeleton } from "@/integrations/outlook_mail/components/fan-out"
import { OutlookRecordList } from "@/integrations/outlook_mail/components/record-list"
import { peopleRows } from "@/integrations/outlook_mail/lib/record-lists"
import { outlookPeopleDetails } from "@/integrations/outlook_mail/lib/tool-details"

const TITLE = "Search Outlook People"
const COLUMNS: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "address", label: "Email", kind: "text", width: "auto" },
  { key: "job_title", label: "Job title", kind: "text" },
  { key: "department", label: "Department", kind: "text" },
]

export const outlookMailPeoplePresenter: ToolRowPresenter = {
  key: "outlook-mail-people",
  matches: (activity) => activity.name === "outlook_mail_search_people",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <OutlookSkeleton label="Searching people…" title={TITLE} />
    }
    const result = parseFanOutData(activity.result, peopleRows)
    if (!result) {
      return null
    }
    return (
      <OutlookRecordList
        columns={COLUMNS}
        defaultOpen={defaultOpen}
        details={outlookPeopleDetails(activity.args)}
        emptyLabel="No people found."
        exportFilename="outlook-people.csv"
        noun="Person"
        nounPlural="People"
        result={result}
        title={TITLE}
      />
    )
  },
}
