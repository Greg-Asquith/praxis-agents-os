// apps/web/src/features/schedules/format.ts

import cronstrue from "cronstrue"

import type { AgentSchedule } from "@/features/schedules/types"
import { formatDateTime, pluralize } from "@/lib/format"

export function scheduleTitle(schedule: AgentSchedule) {
  if (schedule.schedule_type === "cron") {
    return formatCronExpression(schedule.cron_expression)
  }

  if (schedule.schedule_type === "interval") {
    const interval = schedule.interval_minutes ?? 0
    return `Every ${String(interval)} ${pluralize(interval, "minute")}`
  }

  return schedule.run_once_at
    ? `Once ${formatDateTimeInTimeZone(schedule.run_once_at, schedule.timezone)}`
    : "One-time schedule"
}

export function formatScheduleCadence(schedule: AgentSchedule) {
  if (schedule.schedule_type === "cron") {
    return formatCronExpression(schedule.cron_expression)
  }

  if (schedule.schedule_type === "interval") {
    const interval = schedule.interval_minutes ?? 0
    return `Every ${String(interval)} min`
  }

  return schedule.run_once_at
    ? `Once at ${formatDateTimeInTimeZone(schedule.run_once_at, schedule.timezone)}`
    : "Once"
}

export function formatDateTimeInTimeZone(value: string | null | undefined, timezone: string) {
  if (!value) {
    return "Never"
  }

  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value))
  } catch {
    return formatDateTime(value)
  }
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
