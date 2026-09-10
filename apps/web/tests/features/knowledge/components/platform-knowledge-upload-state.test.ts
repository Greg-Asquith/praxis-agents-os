import { afterEach, expect, it, vi } from "vitest"

import { waitForPlatformKnowledgeUpload } from "@/features/knowledge/components/platform-knowledge-upload-state"

const uploaded = {
  id: "file",
  current_revision_id: "revision",
  processing_status: "pending" as const,
}

afterEach(() => vi.useRealTimers())

it("automatically waits through conversion for the confirmed revision", async () => {
  vi.useFakeTimers()
  const getCurrent = vi
    .fn()
    .mockResolvedValueOnce({ ...uploaded, processing_status: "processing" })
    .mockResolvedValueOnce({ ...uploaded, processing_status: "ready" })
  const createDocument = vi.fn()
  const operation = waitForPlatformKnowledgeUpload(
    uploaded,
    getCurrent,
    new AbortController().signal
  ).then(createDocument)
  await vi.advanceTimersByTimeAsync(2_000)
  expect(createDocument).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(2_000)
  await operation
  expect(createDocument).toHaveBeenCalledOnce()
  expect(getCurrent).toHaveBeenCalledTimes(2)
})

it.each([
  [{ ...uploaded, processing_status: "error" }, "File processing failed"],
  [{ ...uploaded, current_revision_id: "replacement", processing_status: "ready" }, "file changed"],
  [{ ...uploaded, id: "another-file", processing_status: "ready" }, "file changed"],
])("rejects failed extraction and changed identities", async (current, message) => {
  vi.useFakeTimers()
  const operation = waitForPlatformKnowledgeUpload(
    uploaded,
    vi.fn().mockResolvedValue(current),
    new AbortController().signal
  )
  const assertion = expect(operation).rejects.toThrow(message)
  await vi.advanceTimersByTimeAsync(2_000)
  await assertion
})

it("cancels polling when the dialog closes", async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const getCurrent = vi.fn()
  const operation = waitForPlatformKnowledgeUpload(uploaded, getCurrent, controller.signal)
  const assertion = expect(operation).rejects.toThrow()
  controller.abort()
  await assertion
  await vi.advanceTimersByTimeAsync(2_000)
  expect(getCurrent).not.toHaveBeenCalled()
  expect(vi.getTimerCount()).toBe(0)
})

it("checks cancellation after an in-flight processing read", async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const getCurrent = vi.fn().mockImplementation(() => {
    controller.abort()
    return Promise.resolve({ ...uploaded, processing_status: "ready" })
  })
  const assertion = expect(
    waitForPlatformKnowledgeUpload(uploaded, getCurrent, controller.signal)
  ).rejects.toThrow()
  await vi.advanceTimersByTimeAsync(2_000)
  await assertion
})

it("bounds waiting and permits retry with the original uploaded revision", async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const getCurrent = vi.fn().mockResolvedValue(uploaded)
  const assertion = expect(
    waitForPlatformKnowledgeUpload(uploaded, getCurrent, controller.signal)
  ).rejects.toThrow("continue the same upload")
  await vi.advanceTimersByTimeAsync(300_000)
  await assertion
  getCurrent.mockResolvedValue({ ...uploaded, processing_status: "ready" })
  const retry = waitForPlatformKnowledgeUpload(uploaded, getCurrent, controller.signal)
  await vi.advanceTimersByTimeAsync(2_000)
  await retry
})
