// apps/web/src/integrations/outlook_mail/presenters/folders.tsx

import type { DataColumn } from "@/components/ui/data-table"
import { OutlookRecordTable } from "@/integrations/outlook_mail/components/record-table"
import { folderRows } from "@/integrations/outlook_mail/lib/record-lists"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

const COLUMNS: DataColumn[] = [
  { key: "name", label: "Folder", kind: "text", width: "auto" },
  { key: "unread_count", label: "Unread", kind: "number", align: "right" },
  { key: "total_count", label: "Messages", kind: "number", align: "right" },
  { key: "child_folder_count", label: "Subfolders", kind: "number", align: "right" },
]

export const outlookMailFoldersPresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "List Outlook Folders results",
  emptyLabel: "No mailboxes returned a result.",
  heading: "List Outlook Folders",
  parseResult: folderRows,
  progressLabel: "Listing folders…",
  render: (rows) => (
    <OutlookRecordTable
      columns={COLUMNS}
      emptyLabel="No folders found."
      exportFilename="outlook-folders.csv"
      noun="Folder"
      nounPlural="Folders"
      rows={rows}
    />
  ),
  tool: "outlook_mail_list_folders",
})
