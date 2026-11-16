// apps/web/src/lib/file-query-keys.ts

import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

// Shared so tool cards and integrations invalidate the same Files caches as the Files feature.
export const baseFilesQueryKeys = createWorkspaceScopedQueryKeys("files")
