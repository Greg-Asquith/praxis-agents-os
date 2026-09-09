import { describe, expect, it } from "vitest"
import type { ApprovalField } from "@/components/tool-ui/approval-types"
import {
  availableFieldOptions,
  fieldOptionsError,
  reconcileFieldOptionEdits,
} from "@/components/tool-ui/field-options"

const provider: ApprovalField = {
  key: "model_provider",
  label: "Image Provider",
  format: "text",
  editable: true,
  min_rows: 0,
  options: ["google", "openai"],
  placeholder: "",
  secondary: false,
}
const ratio: ApprovalField = {
  ...provider,
  key: "aspect_ratio",
  label: "Aspect Ratio",
  secondary: true,
  options: ["1:1", "2:3", "3:2", "16:9"],
  options_by_field: "model_provider",
  options_by_value: { google: ["1:1", "2:3", "3:2", "16:9"], openai: ["1:1", "2:3", "3:2"] },
}
const fields = [provider, ratio]

describe("dependent approval options", () => {
  it.each(["openai", undefined, null])("limits ratios for provider %j", (model_provider) => {
    expect(availableFieldOptions(ratio, { model_provider }, fields)).toEqual(["1:1", "2:3", "3:2"])
  })
  it("offers all Google ratios when Google is selected or is the only provider", () => {
    expect(availableFieldOptions(ratio, { model_provider: "google" }, fields)).toEqual(
      ratio.options
    )
    expect(availableFieldOptions(ratio, {}, [{ ...provider, options: ["google"] }, ratio])).toEqual(
      ratio.options
    )
  })
  it("offers no ratios for an unknown provider", () => {
    expect(availableFieldOptions(ratio, { model_provider: "unknown" }, fields)).toEqual([])
  })
  it("retains valid ratios and omitted defaults when the provider changes", () => {
    for (const aspect_ratio of [undefined, null, "2:3"]) {
      expect(
        reconcileFieldOptionEdits(
          fields,
          { aspect_ratio },
          { model_provider: "openai" },
          "model_provider"
        )
      ).toEqual({ model_provider: "openai" })
    }
  })
  it("checks the edited ratio and preserves unrelated edits", () => {
    expect(
      reconcileFieldOptionEdits(
        fields,
        { aspect_ratio: "1:1" },
        {
          model_provider: "openai",
          aspect_ratio: "16:9",
          prompt: "A panda",
        },
        "model_provider"
      )
    ).toEqual({ model_provider: "openai", aspect_ratio: "1:1", prompt: "A panda" })
  })
  it("blocks an initially unsupported ratio without rejecting omitted defaults", () => {
    expect(fieldOptionsError(fields, { model_provider: "openai", aspect_ratio: "16:9" })).toBe(
      "Choose an available option for Aspect Ratio."
    )
    expect(fieldOptionsError(fields, { model_provider: "openai" })).toBeNull()
  })
})
