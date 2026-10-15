// apps/web/src/integrations/meta_ads/components/campaign-categories.tsx

import { Checkbox } from "@/components/ui/checkbox"
import { Chip, SelectField } from "@/integrations/meta_ads/components/campaign-controls"
import { COUNTRY_OPTIONS } from "@/integrations/meta_ads/lib/campaign-countries"
import {
  CATEGORY_OPTIONS,
  categoryLabel,
  regionName,
  type Category,
} from "@/integrations/meta_ads/lib/create-campaign"

/** Special ad categories as checkboxes, each with the countries it applies to. */
export function CampaignCategories({
  categories,
  disabled,
  onChange,
}: {
  categories: Category[]
  disabled: boolean
  onChange: (categories: Category[]) => void
}) {
  const known: string[] = CATEGORY_OPTIONS.map((item) => item.value)
  const rows = [
    ...CATEGORY_OPTIONS.map((item) => item.value),
    ...categories.map((item) => item.category).filter((value) => !known.includes(value)),
  ]
  const update = (category: string, countries: string[] | null) => {
    const others = categories.filter((item) => item.category !== category)
    onChange(countries === null ? others : [...others, { category, countries }])
  }
  return (
    <div className="grid min-w-0 gap-3">
      <p className="text-foreground/75 text-sm">
        Required for ads about credit, jobs, or housing. Meta then limits how you can target them.
      </p>
      {rows.map((category) => {
        const chosen = categories.find((item) => item.category === category)
        const countries = chosen?.countries ?? []
        return (
          <div className="grid min-w-0 gap-2" key={category}>
            <label className="flex min-h-8 items-center gap-2 text-sm font-medium">
              <Checkbox
                checked={chosen !== undefined}
                disabled={disabled}
                onCheckedChange={(checked) => {
                  update(category, checked ? [] : null)
                }}
              />
              {categoryLabel(category)}
            </label>
            {chosen ? (
              <div className="grid min-w-0 gap-2 pl-6">
                {countries.length > 0 ? (
                  <div className="flex min-w-0 flex-wrap gap-2">
                    {countries.map((code) => (
                      <Chip
                        disabled={disabled}
                        key={code}
                        label={regionName(code)}
                        onRemove={() => {
                          update(
                            category,
                            countries.filter((item) => item !== code)
                          )
                        }}
                      />
                    ))}
                  </div>
                ) : null}
                <SelectField
                  className="max-w-72"
                  disabled={disabled}
                  label="Add a Country"
                  onChange={(code) => {
                    update(category, [...countries, code])
                  }}
                  options={COUNTRY_OPTIONS.filter((item) => !countries.includes(item.value))}
                  placeholder="Choose a country"
                  value={null}
                />
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
