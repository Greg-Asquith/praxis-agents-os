// apps/web/src/integrations/sharepoint/presenters/create-folder.tsx

import { sharePointCreateFolderArgs } from "@/integrations/sharepoint/lib/write-args"
import { sharePointWritePresenter } from "@/integrations/sharepoint/presenters/write-presenter"

export const sharePointCreateFolderPresenter = sharePointWritePresenter({
  tool: "sharepoint_create_folder",
  copy: { verb: "Create", object: "folder", effect: "created" },
  parseArgs: sharePointCreateFolderArgs,
  prompt: "Create this folder in the selected destination. Existing folders and files are kept.",
})
