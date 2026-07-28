// apps/web/src/integrations/bigquery/index.ts

import { BigQueryConnectHelp } from "@/integrations/bigquery/components/connect-help"
import { BigQueryLogo } from "@/integrations/bigquery/components/logo"
import { bigQueryQueryPresenter } from "@/integrations/bigquery/presenters/query"
import { bigQuerySchemaPresenter } from "@/integrations/bigquery/presenters/schema"
import { bigQueryTablesPresenter } from "@/integrations/bigquery/presenters/tables"
import type { IntegrationUiModule } from "@/integrations/contract"

export default {
  catalogDescription:
    "Let agents explore approved datasets and run read-only SQL queries.",
  ConnectHelp: BigQueryConnectHelp,
  icons: { bigquery: BigQueryLogo },
  providerKey: "bigquery",
  toolRowPresenters: [bigQueryTablesPresenter, bigQuerySchemaPresenter, bigQueryQueryPresenter],
} satisfies IntegrationUiModule
