// apps/web/src/features/skills/components/skills-table.tsx

import { Link } from "@tanstack/react-router"
import { PlusIcon, Settings2Icon, SparklesIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { skillDisplayName } from "@/features/skills/format"
import type { Skill } from "@/features/skills/types"
import { formatDateTime, pluralize } from "@/lib/format"

export function SkillsTable({ skills }: { skills: Skill[] }) {
  if (skills.length === 0) {
    return (
      <EmptyState
        action={
          <Button variant="secondary" render={<Link to="/skills/new" />}>
            <PlusIcon data-icon="inline-start" />
            New skill
          </Button>
        }
        description="Create a skill to package instructions and reference documents your agents can activate on demand."
        icon={<SparklesIcon className="size-5" />}
        size="compact"
        title="No skills yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {skills.map((skill) => (
          <SkillMobileRow key={skill.id} skill={skill} />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Documents</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {skills.map((skill) => {
              const documentCount = Object.keys(skill.documentation_refs).length

              return (
                <TableRow key={skill.id}>
                  <TableCell>
                    <div className="flex min-w-40 flex-col gap-1">
                      <Link
                        className="font-medium hover:underline"
                        params={{ skillId: skill.id }}
                        to="/skills/$skillId"
                      >
                        {skillDisplayName(skill)}
                      </Link>
                      {skill.is_favorite ? (
                        <span className="text-muted-foreground text-xs">Favorite</span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-muted-foreground block max-w-md truncate text-sm">
                      {skill.description}
                    </span>
                  </TableCell>
                  <TableCell>
                    {documentCount} {pluralize(documentCount, "document")}
                  </TableCell>
                  <TableCell>
                    <SkillStatusBadges skill={skill} />
                  </TableCell>
                  <TableCell>{formatDateTime(skill.last_used_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      render={<Link to="/skills/$skillId" params={{ skillId: skill.id }} />}
                    >
                      <Settings2Icon data-icon="inline-start" />
                      Configure
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function SkillMobileRow({ skill }: { skill: Skill }) {
  const documentCount = Object.keys(skill.documentation_refs).length

  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{skillDisplayName(skill)}</p>
            {skill.is_favorite ? (
              <p className="text-muted-foreground truncate text-xs">Favorite</p>
            ) : null}
          </div>
          <SkillStatusBadges skill={skill} />
        </div>

        <p className="text-muted-foreground line-clamp-2 text-xs leading-5">{skill.description}</p>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Documents">
            {documentCount} {pluralize(documentCount, "document")}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Last used">
            {formatDateTime(skill.last_used_at)}
          </ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          variant="outline"
          render={<Link to="/skills/$skillId" params={{ skillId: skill.id }} />}
        >
          <Settings2Icon data-icon="inline-start" />
          Configure
        </Button>
      </div>
    </ResponsiveListItem>
  )
}

function SkillStatusBadges({ skill }: { skill: Skill }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={skill.is_active ? "default" : "secondary"}>
        {skill.is_active ? "Active" : "Inactive"}
      </Badge>
      {skill.is_favorite ? <Badge variant="outline">Favorite</Badge> : null}
    </div>
  )
}
