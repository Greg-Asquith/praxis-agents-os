// apps/web/src/features/artifacts/components/artifacts-table.tsx

import { Link } from "@tanstack/react-router"
import { FileCode2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty-state"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ArtifactSummary } from "@/features/artifacts/types"
import { artifactTypeLabel } from "@/features/artifacts/format"
import { formatCompactDate } from "@/lib/format"

export function ArtifactsTable({ artifacts }: { artifacts: ArtifactSummary[] }) {
  if (artifacts.length === 0) {
    return (
      <EmptyState
        description="Artifacts created by agents will appear here with their complete version history."
        icon={<FileCode2Icon className="size-5" />}
        title="No artifacts yet"
      />
    )
  }
  return (
    <>
      <div className="hidden overflow-hidden rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Artifact</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Versions</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {artifacts.map((artifact) => (
              <TableRow key={artifact.id}>
                <TableCell>
                  <Link
                    className="font-medium hover:underline"
                    params={{ artifactId: artifact.id }}
                    to="/artifacts/$artifactId"
                  >
                    {artifact.title}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{artifactTypeLabel(artifact.artifact_type)}</Badge>
                </TableCell>
                <TableCell>{artifact.version_count}</TableCell>
                <TableCell>{formatCompactDate(artifact.updated_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ResponsiveList>
        {artifacts.map((artifact) => (
          <ResponsiveListItem key={artifact.id}>
            <Link
              className="font-medium hover:underline"
              params={{ artifactId: artifact.id }}
              to="/artifacts/$artifactId"
            >
              {artifact.title}
            </Link>
            <dl className="mt-3 grid grid-cols-3 gap-3">
              <ResponsiveListMeta label="Type">
                {artifactTypeLabel(artifact.artifact_type)}
              </ResponsiveListMeta>
              <ResponsiveListMeta label="Versions">{artifact.version_count}</ResponsiveListMeta>
              <ResponsiveListMeta label="Updated">
                {formatCompactDate(artifact.updated_at)}
              </ResponsiveListMeta>
            </dl>
          </ResponsiveListItem>
        ))}
      </ResponsiveList>
    </>
  )
}
