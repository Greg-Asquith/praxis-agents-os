// apps/web/src/integrations/outlook_mail/presenters/folders.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { DataColumn } from "@/components/ui/data-table"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookSkeleton } from "@/integrations/outlook_mail/components/fan-out"
import { OutlookRecordList } from "@/integrations/outlook_mail/components/record-list"
import { folderRows } from "@/integrations/outlook_mail/lib/record-lists"

const TITLE = "List Outlook Folders"
const COLUMNS: DataColumn[] = [
  { key: "name", label: "Folder", kind: "text", width: "auto" },
  { key: "unread_count", label: "Unread", kind: "number", align: "right" },
  { key: "total_count", label: "Messages", kind: "number", align: "right" },
  { key: "child_folder_count", label: "Subfolders", kind: "number", align: "right" },
]

export const outlookMailFoldersPresenter: ToolRowPresenter = {
  key: "outlook-mail-folders",
  matches: (activity) => activity.name === "outlook_mail_list_folders",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <OutlookSkeleton label="Listing folders…" title={TITLE} />
    }
    const result = parseFanOutData(activity.result, folderRows)
    if (!result) {
      return null
    }
    return (
      <OutlookRecordList
        columns={COLUMNS}
        defaultOpen={defaultOpen}
        emptyLabel="No folders found."
        exportFilename="outlook-folders.csv"
        noun="Folder"
        nounPlural="Folders"
        result={result}
        title={TITLE}
      />
    )
  },
}
