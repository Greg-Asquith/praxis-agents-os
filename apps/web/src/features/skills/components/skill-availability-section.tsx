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
  isFavorite,
  onActiveChange,
  onFavoriteChange,
}: {
  isActive: "true" | "false"
  isFavorite: "true" | "false"
  onActiveChange: (isActive: "true" | "false") => void
  onFavoriteChange: (isFavorite: "true" | "false") => void
}) {
  return (
    <FormSection
      description="Control whether agents can be given this skill."
      eyebrow="State"
      title="Availability"
    >
      <FieldGroup className="grid gap-5 sm:grid-cols-2">
        <Field>
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
            Inactive skills cannot be assigned to agents, but their content is kept.
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="skill-favorite">Favorite</FieldLabel>
          <Select
            onValueChange={(value) => {
              onFavoriteChange(value === "true" ? "true" : "false")
            }}
            value={isFavorite}
          >
            <SelectTrigger id="skill-favorite" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectItem value="false">No</SelectItem>
                <SelectItem value="true">Yes</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>Favorites are easier to find when choosing skills.</FieldDescription>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
