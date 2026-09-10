import type { WorkspaceFile } from "@/features/files/types"
import { isFileProcessing } from "@/features/files/processing"

type UploadedRevision = Pick<WorkspaceFile, "id" | "current_revision_id" | "processing_status">

export async function waitForPlatformKnowledgeUpload(
  uploaded: UploadedRevision,
  getCurrent: () => Promise<UploadedRevision>,
  signal: AbortSignal
) {
  let current = uploaded
  for (let attempt = 0; attempt <= 150; attempt += 1) {
    signal.throwIfAborted()
    if (
      uploaded.id !== current.id ||
      uploaded.current_revision_id !== current.current_revision_id
    ) {
      throw new Error(
        "The uploaded file changed. Choose the document again to create a fresh upload."
      )
    }
    if (current.processing_status === "ready") return
    if (!isFileProcessing(current.processing_status)) {
      throw new Error("File processing failed. Choose the document again to retry the upload.")
    }
    if (attempt === 150) break
    await waitForPoll(signal)
    current = await getCurrent()
  }
  signal.throwIfAborted()
  throw new Error(
    "File processing is taking longer than expected. Try again to continue the same upload."
  )
}

function waitForPoll(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException("Upload cancelled", "AbortError"))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort)
      resolve()
    }, 2_000)
    signal.addEventListener("abort", abort, { once: true })
  })
}
