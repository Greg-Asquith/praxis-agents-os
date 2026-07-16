// apps/web/src/features/skills/routes/skills-route.tsx

import { Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useSkillsQuery } from "@/features/skills/api/list-skills"
import { SkillsTable } from "@/features/skills/components/skills-table"

export function SkillsRoute() {
  const { data } = useSkillsQuery({ includeInactive: true, limit: 100 })
  const hasSkills = data.skills.length > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasSkills ? (
            <Button render={<Link to="/skills/new" />}>
              <PlusIcon data-icon="inline-start" />
              New skill
            </Button>
          ) : null
        }
        description="Package reusable instructions and reference documents for agents."
        title="Skills"
      />

      <SkillsTable skills={data.skills} />
    </div>
  )
}
