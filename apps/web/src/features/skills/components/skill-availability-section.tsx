// apps/web/src/features/skills/components/skill-availability-section.tsx

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export function SkillAvailabilitySection({
  isActive,
  onActiveChange,
}: {
  isActive: "true" | "false"
  onActiveChange: (isActive: "true" | "false") => void
}) {
  return (
    <FormSection
      description="Control whether agents can find and use this skill."
      eyebrow="State"
      title="Availability"
    >
      <FieldGroup>
        <Field className="max-w-sm">
          <FieldLabel htmlFor="skill-active">Status</FieldLabel>
          <Select
            onValueChange={(value) => {
              onActiveChange(value === "false" ? "false" : "true")
            }}
            value={isActive}
          >
            <SelectTrigger id="skill-active" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectItem value="true">Active</SelectItem>
                <SelectItem value="false">Inactive</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>
            Agents can't find inactive skills, but their content is kept.
          </FieldDescription>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
