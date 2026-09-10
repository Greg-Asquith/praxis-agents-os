// apps/web/src/integrations/bigquery/provider.ts

import { BigQueryLogo } from "@/integrations/bigquery/components/logo"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"

export const bigQueryProvider: IntegrationProviderUi = {
  contextLabel: "Project",
  externalLabel: "Project ID",
  fallbackDisplayName: "Selected BigQuery project",
  Logo: BigQueryLogo,
  name: "BigQuery",
  providerKey: "bigquery",
}
