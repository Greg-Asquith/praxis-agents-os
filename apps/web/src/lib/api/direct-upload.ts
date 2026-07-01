// apps/web/src/lib/api/direct-upload.ts

import type { SignedUpload } from "@/lib/storage"

export async function uploadFileDirectly(
  upload: SignedUpload,
  file: File,
  maxSizeBytes: number
) {
  if (file.size > maxSizeBytes) {
    throw new Error("Selected file is larger than the upload limit.")
  }

  const response = await fetch(upload.url, {
    body: file,
    credentials: "omit",
    headers: upload.headers,
    method: upload.method,
  })

  if (!response.ok) {
    throw new Error(`Upload failed (${String(response.status)}).`)
  }
}
