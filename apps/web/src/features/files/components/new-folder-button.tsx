// apps/web/src/features/files/components/new-folder-button.tsx

import { useState } from "react"
import { PlusIcon } from "lucide-react"

import { FolderDialog } from "./folder-dialog"
import { Button } from "@/components/ui/button"

export function NewFolderButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button
        onClick={() => {
          setOpen(true)
        }}
        type="button"
        variant="outline"
      >
        <PlusIcon data-icon="inline-start" />
        New Folder
      </Button>
      <FolderDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
