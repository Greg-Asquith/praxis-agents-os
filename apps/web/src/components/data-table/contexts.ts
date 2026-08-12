// apps/web/src/components/data-table/contexts.ts

import { createTableHookContexts } from "@tanstack/react-table"

import type { appTableFeatures } from "@/components/data-table/features"

export const appTableContexts = createTableHookContexts<typeof appTableFeatures>()
