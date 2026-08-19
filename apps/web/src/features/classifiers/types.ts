// apps/web/src/features/classifiers/types.ts

type ClassifierLabel = {
  description: string | null
  label: string
}

export type Classifier = {
  created_at: string
  created_by: string
  description: string
  display_name: string
  id: string
  instructions: string | null
  is_active: boolean
  labels: ClassifierLabel[]
  model: string | null
  model_provider: string | null
  name: string
  updated_at: string
  workspace_id: string
}

export type ClassifiersListResponse = {
  classifiers: Classifier[]
  limit: number
  offset: number
  total: number
}

export type ClassifierCreateRequest = {
  description: string
  display_name: string
  instructions: string | null
  is_active: boolean
  labels: ClassifierLabel[]
  model: string | null
  model_provider: string | null
  name: string
}

export type ClassifierUpdateRequest = ClassifierCreateRequest
