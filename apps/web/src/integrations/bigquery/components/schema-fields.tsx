// apps/web/src/integrations/bigquery/components/schema-fields.tsx

import { Badge } from "@/components/ui/badge"
import { formatBytes } from "@/lib/format"
import type { BigQuerySchema } from "@/integrations/bigquery/lib/results"

export function BigQuerySchemaFields({ schema }: { schema: BigQuerySchema }) {
  return (
    <div className="grid min-w-0 gap-3">
      {schema.description ? (
        <p className="text-muted-foreground text-sm">{schema.description}</p>
      ) : null}
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="secondary">{schema.tableType.replaceAll("_", " ")}</Badge>
        {schema.rowCount !== null ? (
          <Badge variant="outline">{new Intl.NumberFormat().format(schema.rowCount)} rows</Badge>
        ) : null}
        {schema.sizeBytes !== null ? (
          <Badge variant="outline">{formatBytes(schema.sizeBytes)}</Badge>
        ) : null}
        {schema.requiresPartitionFilter ? (
          <Badge variant="warning">Partition filter required</Badge>
        ) : null}
        {schema.clusteringFields.map((field) => (
          <Badge key={field} variant="outline">
            Clustered by {field}
          </Badge>
        ))}
      </div>
      {schema.fields.length > 0 ? (
        <div className="divide-border divide-y">
          {schema.fields.map((field) => (
            <div
              className="grid min-w-0 gap-1 px-3 py-2.5 sm:grid-cols-[minmax(10rem,1fr)_auto]"
              key={field.name}
            >
              <div className="min-w-0">
                <code className="block truncate text-sm">{field.name}</code>
                {field.description ? (
                  <p className="text-muted-foreground mt-0.5 text-xs">{field.description}</p>
                ) : null}
              </div>
              <div className="flex items-start gap-1.5">
                <Badge variant="secondary">{field.type}</Badge>
                <Badge variant="outline">{field.mode || "NULLABLE"}</Badge>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground py-4 text-center text-sm">
          No cached fields for this table.
        </p>
      )}
    </div>
  )
}
