// apps/web/src/features/schedules/format.ts

import cronstrue from "cronstrue"

import type { AgentSchedule, ScheduleType } from "@/features/schedules/types"
import { formatDateTime, formatDateTimeInTimeZone } from "@/lib/format"

import {
  buildSchedulePreviewPayload,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"

export function scheduleTitle(schedule: AgentSchedule) {
  const name = schedule.name?.trim()
  if (!name) {
    return "Unnamed schedule"
  }
  return name
}

export function formatScheduleCadence(schedule: AgentSchedule) {
  return formatScheduleCadenceValues({
    cronExpression: schedule.cron_expression,
    intervalMinutes: schedule.interval_minutes,
    runOnceAt: schedule.run_once_at,
    scheduleType: schedule.schedule_type,
    timezone: schedule.timezone,
  })
}

function formatScheduleCadenceValues({
  cronExpression,
  intervalMinutes,
  runOnceAt,
  scheduleType,
  timezone,
}: {
  cronExpression: string | null | undefined
  intervalMinutes: number | null | undefined
  runOnceAt: string | null | undefined
  scheduleType: ScheduleType
  timezone: string
}) {
  if (scheduleType === "cron") {
    return formatCronExpression(cronExpression)
  }

  if (scheduleType === "interval") {
    return `Every ${String(intervalMinutes ?? 0)} min`
  }

  return runOnceAt ? `Once at ${formatDateTimeInTimeZone(runOnceAt, timezone)}` : "Once"
}

export function formatScheduleNextRun(schedule: AgentSchedule) {
  if (!schedule.is_active) {
    return "Paused"
  }

  return formatDateTime(schedule.next_run_at)
}

export function formatCronExpression(cron: string | null | undefined) {
  if (!cron) {
    return "No schedule"
  }

  try {
    return cronstrue.toString(cron, {
      throwExceptionOnParseError: false,
      use24HourTimeFormat: false,
    })
  } catch {
    return "Custom schedule"
  }
}

export function formatIntervalMinutes(minutes: number | null | undefined) {
  if (!minutes || minutes <= 0) {
    return "No interval"
  }

  if (minutes === 1) {
    return "Every minute"
  }
  if (minutes < 60) {
    return `Every ${String(minutes)} minutes`
  }
  if (minutes === 60) {
    return "Every hour"
  }
  if (minutes < 1440 && minutes % 60 === 0) {
    const hours = minutes / 60
    return hours === 1 ? "Every hour" : `Every ${String(hours)} hours`
  }
  if (minutes === 1440) {
    return "Daily"
  }
  if (minutes === 10080) {
    return "Weekly"
  }

  if (minutes >= 1440) {
    const days = Math.floor(minutes / 1440)
    const remainingHours = Math.floor((minutes % 1440) / 60)
    if (remainingHours === 0) {
      return days === 1 ? "Daily" : `Every ${String(days)} days`
    }
    return `Every ${String(days)}d ${String(remainingHours)}h`
  }

  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  if (remainingMinutes === 0) {
    return hours === 1 ? "Every hour" : `Every ${String(hours)} hours`
  }
  return `Every ${String(hours)}h ${String(remainingMinutes)}m`
}

export function formatScheduleFormCadence(state: ScheduleFormState) {
  const timing = buildSchedulePreviewPayload(state)
  if (!timing) {
    return "Timing needs attention"
  }

  return formatScheduleCadenceValues({
    cronExpression: timing.cron_expression,
    intervalMinutes: timing.interval_minutes,
    runOnceAt: timing.run_once_at,
    scheduleType: timing.schedule_type,
    timezone: timing.timezone ?? state.timezone,
  })
}
