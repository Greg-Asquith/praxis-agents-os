import { describe, expect, it } from "vitest"

import { navigationItemsForRole } from "@/config/navigation"

describe("navigationItemsForRole", () => {
  it.each([null, "member", "admin", "owner"])(
    "keeps the primary navigation focused for the %s role",
    (role) => {
      expect(
        navigationItemsForRole(role).map(({ label, to }) => ({
          label,
          to,
        }))
      ).toEqual([
        { label: "Home", to: "/" },
        { label: "Agents", to: "/agents" },
        { label: "Skills", to: "/skills" },
        { label: "Files", to: "/files" },
        { label: "Schedules", to: "/schedules" },
      ])
    }
  )
})
