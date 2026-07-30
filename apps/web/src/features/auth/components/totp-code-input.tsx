// apps/web/src/features/auth/components/totp-code-input.tsx

import type { ComponentProps } from "react"
import { REGEXP_ONLY_DIGITS } from "input-otp"

import { InputOTP, InputOTPGroup, InputOTPSeparator, InputOTPSlot } from "@/components/ui/input-otp"
import { cn } from "@/lib/utils"

const SLOT_GROUPS = {
  6: [
    [0, 1, 2],
    [3, 4, 5],
  ],
  8: [
    [0, 1, 2, 3],
    [4, 5, 6, 7],
  ],
} as const

type TotpCodeInputProps = Omit<
  ComponentProps<typeof InputOTP>,
  "children" | "maxLength" | "minLength" | "pattern" | "render"
> & {
  invalid?: boolean
  length: 6 | 8
}

export function TotpCodeInput({
  autoComplete = "one-time-code",
  containerClassName,
  invalid = false,
  length,
  ...props
}: TotpCodeInputProps) {
  const [firstGroup, secondGroup] = SLOT_GROUPS[length]

  return (
    <InputOTP
      {...props}
      autoComplete={autoComplete}
      containerClassName={cn("justify-center", containerClassName)}
      maxLength={length}
      minLength={length}
      pattern={REGEXP_ONLY_DIGITS}
    >
      <InputOTPGroup>
        {firstGroup.map((index) => (
          <InputOTPSlot aria-invalid={invalid || undefined} index={index} key={index} />
        ))}
      </InputOTPGroup>
      <InputOTPSeparator />
      <InputOTPGroup>
        {secondGroup.map((index) => (
          <InputOTPSlot aria-invalid={invalid || undefined} index={index} key={index} />
        ))}
      </InputOTPGroup>
    </InputOTP>
  )
}
