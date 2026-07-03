// apps/web/src/features/schedules/components/schedule-cron-model.ts

import { DEFAULT_CRON_EXPRESSION } from "@/features/schedules/components/schedule-form-model"

export type AdvancedCronValues = {
  days: string[]
  hour: string
  minute: string
}

export const CRON_PRESETS = [
  {
    description: "Monday through Friday",
    label: "Every weekday at 9:00 AM",
    value: "0 9 * * 1-5",
  },
  {
    description: "Monday through Friday",
    label: "Every weekday at 6:00 PM",
    value: "0 18 * * 1-5",
  },
  {
    description: "Every day",
    label: "Daily at 8:00 AM",
    value: "0 8 * * *",
  },
  {
    description: "Every day at midnight",
    label: "Daily at midnight",
    value: "0 0 * * *",
  },
  {
    description: "Weekly",
    label: "Every Monday at 9:00 AM",
    value: "0 9 * * 1",
  },
  {
    description: "Weekly",
    label: "Every Friday at 5:00 PM",
    value: "0 17 * * 5",
  },
  {
    description: "Monthly",
    label: "First of month at 9:00 AM",
    value: "0 9 1 * *",
  },
  {
    description: "On the hour",
    label: "Every hour",
    value: "0 * * * *",
  },
  {
    description: "Twice per hour",
    label: "Every 30 minutes",
    value: "*/30 * * * *",
  },
  {
    description: "Four times per hour",
    label: "Every 15 minutes",
    value: "*/15 * * * *",
  },
]

export const DAY_OPTIONS = [
  { label: "Mon", value: "1" },
  { label: "Tue", value: "2" },
  { label: "Wed", value: "3" },
  { label: "Thu", value: "4" },
  { label: "Fri", value: "5" },
  { label: "Sat", value: "6" },
  { label: "Sun", value: "0" },
]

const DEFAULT_ADVANCED_DAYS = ["1", "2", "3", "4", "5"]
const ALL_ADVANCED_DAYS = DAY_OPTIONS.map((day) => day.value)

export const DEFAULT_ADVANCED_CRON: AdvancedCronValues = {
  days: DEFAULT_ADVANCED_DAYS,
  hour: "9",
  minute: "0",
}

export function deriveCronPreset(expression: string) {
  if (CRON_PRESETS.some((preset) => preset.value === expression)) {
    return expression
  }

  if (parseAdvancedCronExpression(expression)) {
    return "advanced"
  }

  return expression.trim() ? "custom" : DEFAULT_CRON_EXPRESSION
}

export function parseAdvancedCronExpression(expression: string): AdvancedCronValues | null {
  const [minute, hour, dayOfMonth, month, dayOfWeek, ...rest] = expression.trim().split(/\s+/)
  if (
    rest.length > 0 ||
    !/^\d{1,2}$/.test(minute ?? "") ||
    !/^\d{1,2}$/.test(hour ?? "") ||
    dayOfMonth !== "*" ||
    month !== "*" ||
    !dayOfWeek
  ) {
    return null
  }

  const minuteNumber = Number(minute)
  const hourNumber = Number(hour)
  if (minuteNumber > 59 || hourNumber > 23) {
    return null
  }

  const days = expandDayPart(dayOfWeek)
  if (!days || days.length === 0) {
    return null
  }

  return {
    days,
    hour: String(hourNumber),
    minute: String(minuteNumber),
  }
}

export function buildAdvancedCron(days: string[], hour: string, minute: string) {
  if (days.length === 0) {
    return ""
  }

  const parsedHour = Number(hour)
  const parsedMinute = Number(minute)
  if (
    !Number.isInteger(parsedHour) ||
    !Number.isInteger(parsedMinute) ||
    parsedHour < 0 ||
    parsedHour > 23 ||
    parsedMinute < 0 ||
    parsedMinute > 59
  ) {
    return ""
  }

  const dayPart = days.length === ALL_ADVANCED_DAYS.length ? "*" : [...days].sort().join(",")
  return `${String(parsedMinute)} ${String(parsedHour)} * * ${dayPart}`
}

function expandDayPart(dayPart: string) {
  if (dayPart === "*") {
    return ALL_ADVANCED_DAYS
  }

  const days = new Set<string>()
  for (const part of dayPart.split(",")) {
    if (/^[0-6]$/.test(part)) {
      days.add(part)
      continue
    }

    const range = /^([0-6])-([0-6])$/.exec(part)
    if (!range) {
      return null
    }

    const start = Number(range[1])
    const end = Number(range[2])
    if (start > end) {
      return null
    }

    for (let day = start; day <= end; day += 1) {
      days.add(String(day))
    }
  }

  return [...days].filter((day) => ALL_ADVANCED_DAYS.includes(day))
}
