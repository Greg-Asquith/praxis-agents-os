// apps/web/src/features/schedules/components/schedule-form-model.ts

import type {
  AgentSchedule,
  ScheduleCreateRequest,
  SchedulePreviewRequest,
  ScheduleType,
  ScheduleUpdateRequest,
} from "@/features/schedules/types"

export const DEFAULT_CRON_EXPRESSION = "0 9 * * 1-5"
const DATE_TIME_LOCAL_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/
const dateTimeFormatters = new Map<string, Intl.DateTimeFormat>()

type DateTimeLocalParts = {
  day: number
  hour: number
  minute: number
  month: number
  second: number
  year: number
}

type ScheduleTimingPayload = Omit<SchedulePreviewRequest, "preview_count">

export type ScheduleFormState = {
  agentId: string
  cronExpression: string
  defaultPrompt: string
  intervalMinutes: string
  isActive: boolean
  runOnceAt: string
  scheduleType: ScheduleType
  timezone: string
}

export type ScheduleFormValidationEntry = {
  fieldId: string
  label: string
  message: string
}

export type ScheduleFormFieldSetter = <K extends keyof ScheduleFormState>(
  field: K,
  value: ScheduleFormState[K]
) => void

export function initialScheduleFormState(schedule: AgentSchedule | null): ScheduleFormState {
  return {
    agentId: schedule?.agent_id ?? "",
    cronExpression: schedule?.cron_expression ?? DEFAULT_CRON_EXPRESSION,
    defaultPrompt: schedule?.default_prompt ?? "",
    intervalMinutes: schedule?.interval_minutes ? String(schedule.interval_minutes) : "60",
    isActive: schedule?.is_active ?? true,
    runOnceAt: schedule?.run_once_at
      ? toDateTimeLocalValue(schedule.run_once_at, schedule.timezone)
      : "",
    scheduleType: schedule?.schedule_type ?? "cron",
    timezone: schedule?.timezone ?? "UTC",
  }
}

export function validateScheduleFormState(state: ScheduleFormState): ScheduleFormValidationEntry[] {
  const entries: ScheduleFormValidationEntry[] = []

  if (!state.agentId) {
    entries.push({
      fieldId: "schedule-agent",
      label: "Agent",
      message: "Choose the agent this schedule should run.",
    })
  }

  if (!state.defaultPrompt.trim()) {
    entries.push({
      fieldId: "schedule-prompt",
      label: "Prompt",
      message: "Prompt is required.",
    })
  }

  if (!state.timezone.trim()) {
    entries.push({
      fieldId: "schedule-timezone",
      label: "Timezone",
      message: "Timezone is required.",
    })
  }

  if (state.scheduleType === "cron" && !state.cronExpression.trim()) {
    entries.push({
      fieldId: "schedule-cron",
      label: "Cron expression",
      message: "Cron expression is required.",
    })
  }

  if (state.scheduleType === "interval") {
    const parsedInterval = parseIntervalMinutes(state.intervalMinutes)
    if (typeof parsedInterval === "string") {
      entries.push({
        fieldId: "schedule-interval",
        label: "Interval",
        message: parsedInterval,
      })
    }
  }

  if (state.scheduleType === "once") {
    if (!state.runOnceAt) {
      entries.push({
        fieldId: "schedule-once",
        label: "Run once at",
        message: "Run once time is required.",
      })
    } else {
      const runOnceAt = toIsoDateTimeInTimeZone(state.runOnceAt, state.timezone.trim() || "UTC")
      if (!runOnceAt) {
        entries.push({
          fieldId: "schedule-once",
          label: "Run once at",
          message: "Run once time is invalid.",
        })
      } else if (new Date(runOnceAt) <= new Date()) {
        entries.push({
          fieldId: "schedule-once",
          label: "Run once at",
          message: "Choose a future time.",
        })
      }
    }
  }

  return entries
}

export function buildSchedulePreviewPayload(
  state: ScheduleFormState
): SchedulePreviewRequest | null {
  const timingPayload = buildScheduleTimingPayload(state)
  if (typeof timingPayload === "string") {
    return null
  }

  return {
    ...timingPayload,
    preview_count: 5,
  }
}

export function buildSchedulePayload(
  state: ScheduleFormState,
  mode: "create"
): ScheduleCreateRequest | string
export function buildSchedulePayload(
  state: ScheduleFormState,
  mode: "edit"
): ScheduleUpdateRequest | string
export function buildSchedulePayload(
  state: ScheduleFormState,
  mode: "create" | "edit"
): ScheduleCreateRequest | ScheduleUpdateRequest | string {
  const validationEntry = validateScheduleFormState(state)[0]
  if (validationEntry) {
    return validationEntry.message
  }

  const timingPayload = buildScheduleTimingPayload(state)
  if (typeof timingPayload === "string") {
    return timingPayload
  }

  const basePayload = {
    ...timingPayload,
    default_prompt: state.defaultPrompt.trim(),
    execution_params: null,
    is_active: state.isActive,
  }

  if (mode === "create") {
    return {
      ...basePayload,
      agent_id: state.agentId,
    }
  }

  return basePayload
}

export function isScheduleFormDirty(current: ScheduleFormState, initial: ScheduleFormState) {
  return (
    current.agentId !== initial.agentId ||
    current.cronExpression !== initial.cronExpression ||
    current.defaultPrompt !== initial.defaultPrompt ||
    current.intervalMinutes !== initial.intervalMinutes ||
    current.isActive !== initial.isActive ||
    current.runOnceAt !== initial.runOnceAt ||
    current.scheduleType !== initial.scheduleType ||
    current.timezone !== initial.timezone
  )
}

function buildScheduleTimingPayload(state: ScheduleFormState): ScheduleTimingPayload | string {
  const timezone = state.timezone.trim()
  if (!timezone) {
    return "Timezone is required."
  }

  if (state.scheduleType === "cron") {
    const cronExpression = state.cronExpression.trim()
    if (!cronExpression) {
      return "Cron expression is required."
    }
    return {
      schedule_type: "cron",
      cron_expression: cronExpression,
      interval_minutes: null,
      run_once_at: null,
      timezone,
    }
  }

  if (state.scheduleType === "interval") {
    const parsedInterval = parseIntervalMinutes(state.intervalMinutes)
    if (typeof parsedInterval === "string") {
      return parsedInterval
    }

    return {
      schedule_type: "interval",
      cron_expression: null,
      interval_minutes: parsedInterval,
      run_once_at: null,
      timezone,
    }
  }

  const runOnceAt = toIsoDateTimeInTimeZone(state.runOnceAt, timezone)
  if (!runOnceAt) {
    return "Run once time is invalid."
  }

  return {
    schedule_type: "once",
    cron_expression: null,
    interval_minutes: null,
    run_once_at: runOnceAt,
    timezone,
  }
}

function parseIntervalMinutes(rawValue: string): number | string {
  const value = rawValue.trim()
  if (!value) {
    return "Interval is required."
  }

  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1) {
    return "Interval must be a whole number of at least 1 minute."
  }

  return parsed
}

function toIsoDateTimeInTimeZone(value: string, timezone: string) {
  const parts = parseDateTimeLocalParts(value)
  if (!parts) {
    return null
  }

  let guess = Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second
  )

  for (let index = 0; index < 4; index += 1) {
    const zonedParts = getDateTimePartsInTimeZone(new Date(guess), timezone)
    if (!zonedParts) {
      return null
    }

    const expectedWallTime = partsToUtcMilliseconds(parts)
    const actualWallTime = partsToUtcMilliseconds(zonedParts)
    const difference = expectedWallTime - actualWallTime
    if (difference === 0) {
      return new Date(guess).toISOString()
    }

    guess += difference
  }

  const finalParts = getDateTimePartsInTimeZone(new Date(guess), timezone)
  return finalParts && dateTimePartsEqual(parts, finalParts) ? new Date(guess).toISOString() : null
}

function parseDateTimeLocalParts(value: string): DateTimeLocalParts | null {
  const match = DATE_TIME_LOCAL_PATTERN.exec(value)
  if (!match) {
    return null
  }

  const parts = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6] ?? "0"),
  }
  const normalizedDate = new Date(
    Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
  )

  if (
    normalizedDate.getUTCFullYear() !== parts.year ||
    normalizedDate.getUTCMonth() !== parts.month - 1 ||
    normalizedDate.getUTCDate() !== parts.day ||
    normalizedDate.getUTCHours() !== parts.hour ||
    normalizedDate.getUTCMinutes() !== parts.minute ||
    normalizedDate.getUTCSeconds() !== parts.second
  ) {
    return null
  }

  return parts
}

function getDateTimePartsInTimeZone(date: Date, timezone: string): DateTimeLocalParts | null {
  try {
    const formatter = getDateTimeFormatter(timezone)
    const parts = Object.fromEntries(
      formatter
        .formatToParts(date)
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value])
    )
    return {
      year: Number(parts["year"]),
      month: Number(parts["month"]),
      day: Number(parts["day"]),
      hour: Number(parts["hour"]),
      minute: Number(parts["minute"]),
      second: Number(parts["second"]),
    }
  } catch {
    return null
  }
}

function getDateTimeFormatter(timezone: string) {
  const cached = dateTimeFormatters.get(timezone)
  if (cached) {
    return cached
  }

  const formatter = new Intl.DateTimeFormat("en-US", {
    calendar: "iso8601",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone: timezone,
    year: "numeric",
  })
  dateTimeFormatters.set(timezone, formatter)
  return formatter
}

function partsToUtcMilliseconds(parts: DateTimeLocalParts) {
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
}

function dateTimePartsEqual(left: DateTimeLocalParts, right: DateTimeLocalParts) {
  return (
    left.year === right.year &&
    left.month === right.month &&
    left.day === right.day &&
    left.hour === right.hour &&
    left.minute === right.minute &&
    left.second === right.second
  )
}

function toDateTimeLocalValue(value: string, timezone: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ""
  }

  const parts = getDateTimePartsInTimeZone(date, timezone)
  if (!parts) {
    return ""
  }

  return `${padDateTimePart(parts.year, 4)}-${padDateTimePart(parts.month)}-${padDateTimePart(
    parts.day
  )}T${padDateTimePart(parts.hour)}:${padDateTimePart(parts.minute)}`
}

function padDateTimePart(value: number, length = 2) {
  return String(value).padStart(length, "0")
}
