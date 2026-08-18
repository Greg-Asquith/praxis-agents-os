// apps/web/src/features/files/api/lis-folders.ts

import { queryOptions } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileFolderListResponse } from "../types"
import { apiRequest } from "@/lib/api/client"

export const foldersQueryOptions = () =>
  queryOptions({
    queryKey: filesQueryKeys.folders(),
    queryFn: () => apiRequest<FileFolderListResponse>("/files/folders"),
    staleTime: 30_000,
  })
