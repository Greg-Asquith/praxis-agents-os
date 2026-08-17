import { describe, expect, it } from "vitest"

import {
  authSuccessPath,
  invitationTokenFromRedirect,
  safeRedirectPath,
  validateAuthRedirectSearch,
} from "@/lib/safe-redirect"

describe("safe redirect paths", () => {
  it.each([
    ["/profile", "/profile"],
    ["/invitations/accept?token=x", "/invitations/accept?token=x"],
    ["https://attacker.example/path", null],
    ["//attacker.example/path", null],
    [String.raw`/\attacker.example/path`, null],
    ["/profile\t/attacker.example", null],
    ["/profile path", null],
    ["profile", null],
    [null, null],
  ])("validates %s", (value, expected) => {
    expect(safeRedirectPath(value)).toBe(expected)
  })

  it("keeps only validated auth search", () => {
    expect(validateAuthRedirectSearch({ redirect: "/profile" })).toEqual({
      redirect: "/profile",
    })
    expect(validateAuthRedirectSearch({ redirect: "https://attacker.example" })).toEqual({})
  })

  it("sends password-login success to a safe return path and rejects an unsafe one", () => {
    expect(authSuccessPath("/invitations/accept?token=invite-token")).toBe(
      "/invitations/accept?token=invite-token"
    )
    expect(authSuccessPath("https://attacker.example/path")).toBe("/")
  })

  it("extracts invitation tokens only from the invitation route", () => {
    expect(invitationTokenFromRedirect("/invitations/accept?token=invite-token")).toBe(
      "invite-token"
    )
    expect(invitationTokenFromRedirect("/profile?token=invite-token")).toBeNull()
    expect(invitationTokenFromRedirect("//attacker.example/?token=invite-token")).toBeNull()
  })
})
