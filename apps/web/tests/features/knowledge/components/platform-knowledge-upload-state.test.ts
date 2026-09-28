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
