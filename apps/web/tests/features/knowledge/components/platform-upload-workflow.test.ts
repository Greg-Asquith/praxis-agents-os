import type * as ReactModule from "react"
import type * as QueryModule from "@tanstack/react-query"
import type { ReactElement, SyntheticEvent } from "react"
import { afterEach, expect, it, vi } from "vitest"

import { DocumentUploadButton } from "@/features/knowledge/components/document-upload-button"

const mocks = vi.hoisted(() => ({
  upload: vi.fn(),
  create: vi.fn(),
  read: vi.fn(),
  state: vi.fn(),
}))

vi.mock("react", async (original) => ({
  ...(await original<typeof ReactModule>()),
  useState: mocks.state,
  useId: () => "upload-input",
  useRef: () => ({ current: null }),
  useEffect: vi.fn(),
}))
vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof QueryModule>()),
  useQueryClient: () => ({ fetchQuery: mocks.read }),
}))
vi.mock("@/features/files/api/platform-upload-file", () => ({
  usePlatformUploadFileMutation: () => ({ mutateAsync: mocks.upload }),
}))
vi.mock("@/features/knowledge/api/platform-create-document-from-file", () => ({
  usePlatformCreateDocumentFromFileMutation: () => ({ mutateAsync: mocks.create }),
}))
vi.mock("@/features/knowledge/api/create-document-from-file", () => ({
  useCreateDocumentFromFileMutation: () => ({ isPending: false }),
}))

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetAllMocks()
})

it("creates the pinned Knowledge draft after processing from one submission", async () => {
  vi.useFakeTimers()
  vi.stubGlobal(
    "FormData",
    class {
      get() {
        return "Guidance"
      }
    }
  )
  const file = new File(["document"], "Guidance.pdf", { type: "application/pdf" })
  for (const state of [file, false, null, false, null, false]) {
    mocks.state.mockReturnValueOnce([state, vi.fn()])
  }
  const uploaded = { id: "file", current_revision_id: "revision", processing_status: "pending" }
  mocks.upload.mockResolvedValue(uploaded)
  mocks.read
    .mockResolvedValueOnce({ ...uploaded, processing_status: "processing" })
    .mockResolvedValueOnce({ ...uploaded, processing_status: "ready" })
  mocks.create.mockResolvedValue({ id: "document" })
  const onSaved = vi.fn()
  const form = DocumentUploadButton({ platform: true, onSaved }) as ReactElement<{
    onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void
  }>
  const target = {} as HTMLFormElement
  const event: SyntheticEvent<HTMLFormElement> = {
    nativeEvent: new Event("submit"),
    currentTarget: target,
    target,
    bubbles: true,
    cancelable: true,
    defaultPrevented: false,
    eventPhase: 2,
    isTrusted: false,
    preventDefault: vi.fn(),
    isDefaultPrevented: () => false,
    stopPropagation: vi.fn(),
    isPropagationStopped: () => false,
    persist: vi.fn(),
    timeStamp: 0,
    type: "submit",
  }
  form.props.onSubmit(event)
  form.props.onSubmit(event)
  await vi.advanceTimersByTimeAsync(2_000)
  expect(mocks.upload).toHaveBeenCalledOnce()
  expect(mocks.create).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(2_000)
  expect(mocks.create).toHaveBeenCalledExactlyOnceWith({
    file_id: "file",
    file_revision_id: "revision",
    title: "Guidance",
  })
  expect(onSaved).toHaveBeenCalledOnce()
})
