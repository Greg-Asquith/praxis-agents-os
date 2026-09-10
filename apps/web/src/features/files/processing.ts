import type { FileProcessingStatus } from "./types"

export function isFileProcessing(status: FileProcessingStatus | undefined) {
  return status === "pending" || status === "processing"
}
