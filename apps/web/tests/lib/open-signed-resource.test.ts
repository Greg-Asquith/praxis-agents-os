import { afterEach, describe, expect, it, vi } from "vitest"

import { SignedResourceOpenError, openSignedResource } from "@/lib/open-signed-resource"

type ReservedWindow = {
  close: ReturnType<typeof vi.fn>
  document: {
    createElement: ReturnType<typeof vi.fn>
    head: { append: ReturnType<typeof vi.fn> }
  }
  location: { replace: ReturnType<typeof vi.fn> }
  opener: unknown
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("openSignedResource", () => {
  it("reserves a tab before requesting the signed URL and navigates it", async () => {
    const reservedWindow = createReservedWindow()
    const events: string[] = []
    const open = vi.fn(() => {
      events.push("reserve")
      return reservedWindow
    })
    setWindowOpen(open)

    await openSignedResource(() => {
      events.push("grant")
      return Promise.resolve("https://signed.example/resource")
    })

    expect(events).toEqual(["reserve", "grant"])
    expect(open).toHaveBeenCalledWith("about:blank", "_blank")
    expect(reservedWindow.location.replace).toHaveBeenCalledWith("https://signed.example/resource")
    expect(reservedWindow.close).not.toHaveBeenCalled()
  })

  it("returns an actionable typed error when the popup is blocked", async () => {
    setWindowOpen(vi.fn(() => null))
    const createUrl = vi.fn(() => Promise.resolve("https://signed.example/resource"))

    const error = await openSignedResource(createUrl).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(SignedResourceOpenError)
    expect(error).toMatchObject({
      code: "popup_blocked",
      message: "Allow pop-ups for this site, then try again.",
    })
    expect(createUrl).not.toHaveBeenCalled()
  })

  it("closes the reserved tab when the grant fails", async () => {
    const reservedWindow = createReservedWindow()
    setWindowOpen(vi.fn(() => reservedWindow))
    const grantError = new Error("Grant failed")

    await expect(openSignedResource(() => Promise.reject(grantError))).rejects.toBe(grantError)

    expect(reservedWindow.close).toHaveBeenCalledOnce()
    expect(reservedWindow.location.replace).not.toHaveBeenCalled()
  })

  it("removes the opener and sets a no-referrer policy before requesting a grant", async () => {
    const reservedWindow = createReservedWindow()
    setWindowOpen(vi.fn(() => reservedWindow))

    await openSignedResource(() => {
      expect(reservedWindow.opener).toBeNull()
      expect(reservedWindow.document.head.append).toHaveBeenCalledWith({
        content: "no-referrer",
        name: "referrer",
      })
      return Promise.resolve("https://signed.example/resource")
    })
  })

  it("closes the reserved tab when opener isolation fails", async () => {
    const reservedWindow = createReservedWindow()
    Object.defineProperty(reservedWindow, "opener", {
      configurable: true,
      get: () => ({}),
      set: () => undefined,
    })
    setWindowOpen(vi.fn(() => reservedWindow))

    await expect(
      openSignedResource(() => Promise.resolve("https://signed.example/resource"))
    ).rejects.toMatchObject({ code: "popup_isolation_failed" })
    expect(reservedWindow.close).toHaveBeenCalledOnce()
    expect(reservedWindow.location.replace).not.toHaveBeenCalled()
  })

  it("closes the reserved tab when navigation fails", async () => {
    const reservedWindow = createReservedWindow()
    const navigationError = new Error("Navigation failed")
    reservedWindow.location.replace.mockImplementation(() => {
      throw navigationError
    })
    setWindowOpen(vi.fn(() => reservedWindow))

    await expect(
      openSignedResource(() => Promise.resolve("https://signed.example/resource"))
    ).rejects.toMatchObject({ code: "navigation_failed" })
    expect(reservedWindow.close).toHaveBeenCalledOnce()
  })
})

function createReservedWindow(): ReservedWindow {
  return {
    close: vi.fn(),
    document: {
      createElement: vi.fn(() => ({ content: "", name: "" })),
      head: { append: vi.fn() },
    },
    location: { replace: vi.fn() },
    opener: {},
  }
}

function setWindowOpen(open: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("window", { open })
}
