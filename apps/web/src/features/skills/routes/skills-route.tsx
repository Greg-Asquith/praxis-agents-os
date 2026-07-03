// apps/web/src/features/skills/routes/skills-route.tsx

import { Link } from "@tanstack/react-router"
import { FileTextIcon, PlusIcon, SparklesIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { MetricCard } from "@/components/ui/metric-card"
import { useSkillsQuery } from "@/features/skills/api/list-skills"
import { SkillsTable } from "@/features/skills/components/skills-table"
import { pluralize } from "@/lib/format"

export function SkillsRoute() {
  const { data } = useSkillsQuery({ includeInactive: true, limit: 100 })
  const activeCount = data.skills.filter((skill) => skill.is_active).length
  const documentCount = data.skills.reduce(
    (total, skill) => total + Object.keys(skill.documentation_refs).length,
    0
  )
  const hasSkills = data.skills.length > 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Agent runtime</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Skills</h1>
        </div>
        {hasSkills ? (
          <Button render={<Link to="/skills/new" />}>
            <PlusIcon data-icon="inline-start" />
            New skill
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          description={`${String(data.total)} ${pluralize(data.total, "skill")} in this workspace`}
          icon={<SparklesIcon className="size-4" />}
          title="Total skills"
        />
        <MetricCard
          description={`${String(activeCount)} ${pluralize(activeCount, "skill")} available for agents`}
          title="Active"
        />
        <MetricCard
          description={`${String(documentCount)} ${pluralize(documentCount, "document")} uploaded`}
          icon={<FileTextIcon className="size-4" />}
          title="Documents"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace skills</CardTitle>
          <CardDescription>
            Create reusable instruction packages and reference documents for agents.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SkillsTable skills={data.skills} />
        </CardContent>
      </Card>
    </div>
  )
}
