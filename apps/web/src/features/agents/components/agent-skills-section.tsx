// apps/web/src/features/agents/components/agent-skills-section.tsx

import { useMemo, useState } from "react"
import { PlusIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type {
  AgentFormFieldSetter,
  AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { AgentFormSection } from "@/features/agents/components/agent-form-section"
import { skillDisplayName } from "@/features/skills/format"
import type { Skill } from "@/features/skills/types"

const NO_SKILL_SELECTION = "None"

export function AgentSkillsSection({
  setField,
  skillIds,
  skills,
}: {
  setField: AgentFormFieldSetter
  skillIds: AgentFormState["skillIds"]
  skills: Skill[]
}) {
  const [skillSelection, setSkillSelection] = useState(NO_SKILL_SELECTION)
  const skillIdSet = useMemo(() => new Set(skillIds), [skillIds])
  const skillById = useMemo(() => new Map(skills.map((skill) => [skill.id, skill])), [skills])
  const availableSkills = useMemo(
    () => skills.filter((skill) => skill.is_active && !skillIdSet.has(skill.id)),
    [skillIdSet, skills]
  )
  const effectiveSkillSelection = availableSkills.some((skill) => skill.id === skillSelection)
    ? skillSelection
    : NO_SKILL_SELECTION
  const selectedSkills = skillIds.map((skillId) => ({
    id: skillId,
    skill: skillById.get(skillId) ?? null,
  }))

  function addSkill() {
    const skillId =
      effectiveSkillSelection !== NO_SKILL_SELECTION
        ? effectiveSkillSelection
        : availableSkills[0]?.id
    if (!skillId) {
      return
    }

    setField("skillIds", skillIds.includes(skillId) ? skillIds : [...skillIds, skillId])
    setSkillSelection(NO_SKILL_SELECTION)
  }

  function removeSkill(skillId: string) {
    setField(
      "skillIds",
      skillIds.filter((value) => value !== skillId)
    )
  }

  return (
    <AgentFormSection
      description="Attach active workspace skills this agent can activate during a run."
      eyebrow="Skills"
      title="Attached skills"
    >
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="agent-skill">Attach skill</FieldLabel>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select
              disabled={availableSkills.length === 0}
              onValueChange={(value) => {
                setSkillSelection(value ?? NO_SKILL_SELECTION)
              }}
              value={effectiveSkillSelection}
            >
              <SelectTrigger id="agent-skill" className="w-full">
                <SelectValue placeholder="Select an active skill" />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectItem value={NO_SKILL_SELECTION} disabled>
                    Select an active skill
                  </SelectItem>
                  {availableSkills.map((skill) => (
                    <SelectItem key={skill.id} label={skillDisplayName(skill)} value={skill.id}>
                      <span className="flex min-w-0 flex-col items-start">
                        <span className="truncate">{skillDisplayName(skill)}</span>
                        <span className="text-muted-foreground truncate text-xs">{skill.name}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              disabled={availableSkills.length === 0}
              onClick={addSkill}
              type="button"
              variant="outline"
            >
              <PlusIcon data-icon="inline-start" />
              Attach
            </Button>
          </div>
          <FieldDescription>
            Only active skills can be attached. Inactive attached skills remain visible until
            removed.
          </FieldDescription>
        </Field>

        <div className="flex flex-col gap-2">
          {selectedSkills.length === 0 ? (
            <p className="bg-muted/30 text-muted-foreground rounded-lg p-3 text-sm">
              This agent has no attached skills.
            </p>
          ) : (
            selectedSkills.map(({ id, skill }) => {
              const label = skill ? skillDisplayName(skill) : "Unavailable skill"
              const description =
                skill?.description ?? `Skill id: ${id}. This skill is no longer available.`

              return (
                <div
                  className="flex min-w-0 items-center justify-between gap-3 rounded-md border p-3"
                  key={id}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{label}</p>
                    <p className="text-muted-foreground truncate text-xs">{description}</p>
                  </div>
                  <Button
                    aria-label={`Remove ${label}`}
                    onClick={() => {
                      removeSkill(id)
                    }}
                    size="icon-sm"
                    type="button"
                    variant="outline"
                  >
                    <XIcon />
                  </Button>
                </div>
              )
            })
          )}
        </div>
      </FieldGroup>
    </AgentFormSection>
  )
}
