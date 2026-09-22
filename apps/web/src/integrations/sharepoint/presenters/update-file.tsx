// apps/web/src/integrations/sharepoint/presenters/update-file.tsx

import { sharePointUpdateFileArgs } from "@/integrations/sharepoint/lib/write-args"
import { sharePointWritePresenter } from "@/integrations/sharepoint/presenters/write-presenter"

export const sharePointUpdateFilePresenter = sharePointWritePresenter({
  tool: "sharepoint_update_file",
  copy: { verb: "Update", object: "file", effect: "replaced" },
  parseArgs: sharePointUpdateFileArgs,
  prompt:
    "Replace this file with the reviewed content. SharePoint keeps the previous version. A changed version stops the replacement.",
})
