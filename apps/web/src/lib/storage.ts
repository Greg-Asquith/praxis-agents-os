// apps/web/src/lib/storage.ts

export type StorageObjectRef = {
  bucket: "public" | "private"
  key: string
}

export type SignedUpload = {
  ref: StorageObjectRef
  url: string
  method: "PUT"
  headers: Record<string, string>
  expires_at: string
}

export type AssetUploadRequest = {
  filename: string
  content_type: string
  size_bytes: number
}

export type AssetUploadGrant = {
  upload: SignedUpload
  upload_token: string
  max_size_bytes: number
  expires_at: string
}

export type AssetConfirmRequest = {
  upload_token: string
}
