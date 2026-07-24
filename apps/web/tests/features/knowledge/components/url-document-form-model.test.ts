// apps/web/tests/features/knowledge/components/url-document-form-model.test.ts

import { describe, expect, it } from "vitest"

import {
  buildUrlDocumentPayload,
  validateUrlDocumentForm,
} from "@/features/knowledge/components/url-document-form-model"

describe("URL knowledge document form", () => {
  it("rejects missing titles and non-HTTP URLs", () => {
    expect(
      validateUrlDocumentForm({
        isPrivate: false,
        title: "",
        url: "ftp://example.com/file",
      }).map((entry) => entry.message)
    ).toEqual(["Title is required.", "Enter a valid HTTP or HTTPS URL."])
  })

  it("builds a trimmed request", () => {
    expect(
      buildUrlDocumentPayload({
        isPrivate: true,
        title: "  Handbook  ",
        url: "  https://example.com/handbook  ",
      })
    ).toEqual({
      is_private: true,
      title: "Handbook",
      url: "https://example.com/handbook",
    })
  })
})
