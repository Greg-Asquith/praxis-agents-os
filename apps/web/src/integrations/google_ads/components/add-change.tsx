// apps/web/src/integrations/google_ads/components/add-change.tsx

import { useState } from "react"

import { SelectField } from "@/integrations/ads/components/controls"

export type AddableTarget<S extends string, V> = {
  key: string
  name: string
  options: readonly { setting: S; value: V }[]
}

/** Adds a setting the agent didn't propose to one object in the request, at its live value. */
export function AddChange<S extends string, V>({
  disabled,
  noun,
  onAdd,
  targets,
  titles,
}: {
  disabled: boolean
  // The object's name on the card, such as "Campaign".
  noun: string
  onAdd: (key: string, setting: S, value: V) => void
  targets: readonly AddableTarget<S, V>[]
  titles: Record<S, string>
}) {
  const choices = targets.filter((item) => item.options.length > 0)
  const [chosen, setChosen] = useState<string | null>(null)
  const sole = choices.length === 1 && targets.length === 1 ? choices[0] : undefined
  const target = sole ?? choices.find((item) => item.key === chosen)
  if (choices.length === 0) return null
  return (
    <div className="flex flex-wrap items-end gap-3">
      {sole ? null : (
        <SelectField
          className="w-60"
          disabled={disabled}
          label={noun}
          onChange={setChosen}
          options={choices.map((item) => ({ value: item.key, label: item.name }))}
          placeholder={`Choose a ${noun.toLowerCase()}`}
          value={target?.key ?? null}
        />
      )}
      <SelectField
        className="w-60"
        disabled={disabled || !target}
        label="Add a Change"
        onChange={(setting) => {
          const option = target?.options.find((item) => item.setting === setting)
          if (target && option) onAdd(target.key, option.setting, option.value)
        }}
        options={(target?.options ?? []).map((item) => ({
          value: item.setting,
          label: titles[item.setting],
        }))}
        placeholder="Choose a setting"
        value={null}
      />
    </div>
  )
}
