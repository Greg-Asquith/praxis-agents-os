// apps/web/src/lib/api/direct-upload.ts

import type { SignedUpload } from "@/features/storage/types"

export async function uploadFileDirectly(
  upload: SignedUpload,
  file: File,
  maxSizeBytes: number,
  onProgress?: (fraction: number) => void
) {
  if (file.size > maxSizeBytes) {
    throw new Error("Selected file is larger than the upload limit.")
  }
  if (onProgress) {
    await uploadWithProgress(upload, file, onProgress)
    return
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

// fetch can't report upload progress, so this path uses XMLHttpRequest.
function uploadWithProgress(
  upload: SignedUpload,
  file: File,
  onProgress: (fraction: number) => void
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open(upload.method, upload.url)
    request.withCredentials = false
    for (const [name, value] of Object.entries(upload.headers)) {
      request.setRequestHeader(name, value)
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total)
      }
    }
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve()
      } else {
        reject(new Error(`Upload failed (${String(request.status)}).`))
      }
    }
    request.onerror = () => {
      reject(new Error("Upload failed. Check your connection and try again."))
    }
    request.send(file)
  })
}
