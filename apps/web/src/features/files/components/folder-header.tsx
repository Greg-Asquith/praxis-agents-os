// apps/web/src/features/files/components/folder-header.tsx

import type { FileFolder } from "../types"
import { FolderActions } from "./folder-actions"

export function FolderHeader({ folder, onDeleted }: { folder: FileFolder; onDeleted: () => void }) {
  return <FolderActions folder={folder} onDeleted={onDeleted} triggerVariant="outline" />
}
