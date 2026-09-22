// apps/web/src/integrations/sharepoint/presenters/write-file.tsx

import { sharePointWriteFileArgs } from "@/integrations/sharepoint/lib/write-args"
import { sharePointWritePresenter } from "@/integrations/sharepoint/presenters/write-presenter"

export const sharePointWriteFilePresenter = sharePointWritePresenter({
  tool: "sharepoint_write_file",
  copy: { verb: "Save", object: "file", effect: "saved" },
  parseArgs: sharePointWriteFileArgs,
  prompt:
    "Save the reviewed content as a new file in the selected destination. No existing file is replaced.",
})
