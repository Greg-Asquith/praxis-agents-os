// apps/web/src/features/schedules/types.ts

export type ScheduleType = "cron" | "interval" | "once"

export type ScheduleHealth = "healthy" | "retrying" | "needs_attention" | "cancelled"

export type ScheduleRunStatus =
  | "pending"
  | "claimed"
  | "accepted"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "retryable_failed"
  | "terminal_failed"
  | "cancelled"

export type AgentScheduleRun = {
  id: string
  schedule_id: string
  scheduled_for: string
  status: ScheduleRunStatus
  attempt_count: number
  conversation_id: string | null
  agent_run_id: string | null
  accepted_at: string | null
  completed_at: string | null
  failed_at: string | null
  last_error_code: string | null
  last_error_message: string | null
  created_at: string
  health: ScheduleHealth
}

export type AgentSchedule = {
  id: string
  agent_id: string
  user_id: string
  workspace_id: string
  schedule_type: ScheduleType
  cron_expression: string | null
  interval_minutes: number | null
  run_once_at: string | null
  timezone: string
  default_prompt: string | null
  execution_params: Record<string, unknown> | null
  is_active: boolean
  last_run_at: string | null
  next_run_at: string | null
  created_at: string
  updated_at: string
  health: ScheduleHealth
  latest_run: AgentScheduleRun | null
}

export type SchedulesListResponse = {
  items: AgentSchedule[]
  total: number
  limit: number
  offset: number
}

export type ScheduleRunsListResponse = {
  items: AgentScheduleRun[]
  total: number
  limit: number
  offset: number
}

export type ScheduleCreateRequest = {
  agent_id: string
  schedule_type: ScheduleType
  cron_expression?: string | null
  interval_minutes?: number | null
  run_once_at?: string | null
  timezone?: string | null
  default_prompt: string
  execution_params?: Record<string, unknown> | null
  is_active?: boolean
}

export type ScheduleUpdateRequest = Partial<Omit<ScheduleCreateRequest, "agent_id">>

export type SchedulePreviewRequest = {
  schedule_type: ScheduleType
  cron_expression?: string | null
  interval_minutes?: number | null
  run_once_at?: string | null
  timezone?: string | null
  preview_count?: number
}

export type SchedulePreviewResponse = {
  next_runs: string[]
}
