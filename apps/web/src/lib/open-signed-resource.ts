// apps/web/src/lib/open-signed-resource.ts

export class SignedResourceOpenError extends Error {
  readonly code: "popup_blocked" | "popup_isolation_failed" | "navigation_failed"

  constructor(code: SignedResourceOpenError["code"], message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = "SignedResourceOpenError"
    this.code = code
  }
}

export async function openSignedResource(createUrl: () => Promise<string>) {
  const reservedWindow = window.open("about:blank", "_blank")
  if (!reservedWindow) {
    throw new SignedResourceOpenError(
      "popup_blocked",
      "Allow pop-ups for this site, then try again."
    )
  }

  try {
    isolateReservedWindow(reservedWindow)
  } catch (error) {
    reservedWindow.close()
    throw new SignedResourceOpenError(
      "popup_isolation_failed",
      "Your browser could not open this resource securely. Try again or use another browser.",
      { cause: error }
    )
  }

  let url: string
  try {
    url = await createUrl()
  } catch (error) {
    reservedWindow.close()
    throw error
  }

  try {
    reservedWindow.location.replace(url)
  } catch (error) {
    reservedWindow.close()
    throw new SignedResourceOpenError(
      "navigation_failed",
      "The resource could not be opened. Check your browser settings and try again.",
      { cause: error }
    )
  }
}

function isolateReservedWindow(reservedWindow: Window) {
  reservedWindow.opener = null
  if (reservedWindow.opener !== null) {
    throw new Error("The reserved window retained an opener reference.")
  }

  const referrerPolicy = reservedWindow.document.createElement("meta")
  referrerPolicy.name = "referrer"
  referrerPolicy.content = "no-referrer"
  reservedWindow.document.head.append(referrerPolicy)
}
