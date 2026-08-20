// apps/web/src/lib/chart-export.ts

const SVG_PRESENTATION_PROPERTIES = [
  "color",
  "display",
  "fill",
  "fill-opacity",
  "font-family",
  "font-size",
  "font-style",
  "font-weight",
  "letter-spacing",
  "opacity",
  "stroke",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-opacity",
  "stroke-width",
  "text-anchor",
  "visibility",
] as const

type ChartExportDetails = {
  caption: string | null
  subtitle: string | null
  title: string
}

type LegendItem = {
  color: string
  label: string
}

const EXPORT_PADDING = 24
const TITLE_FONT = "600 18px ui-sans-serif, system-ui, sans-serif"
const BODY_FONT = "12px ui-sans-serif, system-ui, sans-serif"
const CAPTION_FONT = "11px ui-sans-serif, system-ui, sans-serif"

export async function downloadChartPng(
  element: HTMLElement,
  details: ChartExportDetails
): Promise<void> {
  const surface = element.querySelector<HTMLElement>("[data-chart-surface]")
  // Legend icons are svgs too; the plot svg is the direct child of the recharts wrapper.
  const source = surface?.querySelector<SVGSVGElement>(".recharts-wrapper > svg.recharts-surface")
  if (!surface || !source) {
    throw new Error("The chart is not ready to export.")
  }

  const bounds = source.getBoundingClientRect()
  if (bounds.width < 40 || bounds.height < 40) {
    throw new Error("The chart is not ready to export.")
  }
  const plotWidth = Math.max(1, Math.ceil(bounds.width))
  const plotHeight = Math.max(1, Math.ceil(bounds.height))
  const width = plotWidth + EXPORT_PADDING * 2
  const surfaceStyles = getComputedStyle(surface)
  const rootStyles = getComputedStyle(document.documentElement)
  const background =
    opaqueColor(surfaceStyles.backgroundColor) ?? resolvedToken(rootStyles, "--card") ?? "#ffffff"
  const foreground =
    opaqueColor(getComputedStyle(element).color) ??
    resolvedToken(rootStyles, "--card-foreground") ??
    "#111111"
  const muted = resolvedToken(rootStyles, "--muted-foreground") ?? foreground

  const measuringCanvas = document.createElement("canvas")
  const measuringContext = measuringCanvas.getContext("2d")
  if (!measuringContext) {
    throw new Error("This browser cannot export the chart.")
  }
  const textWidth = width - EXPORT_PADDING * 2
  measuringContext.font = TITLE_FONT
  const titleLines = wrapText(measuringContext, details.title, textWidth)
  measuringContext.font = BODY_FONT
  const subtitleLines = details.subtitle
    ? wrapText(measuringContext, details.subtitle, textWidth)
    : []
  measuringContext.font = CAPTION_FONT
  const captionLines = details.caption ? wrapText(measuringContext, details.caption, textWidth) : []
  const legendItems = readLegend(surface)
  measuringContext.font = BODY_FONT
  const legendRows = packLegendRows(measuringContext, legendItems, textWidth)

  const headerHeight =
    titleLines.length * 23 + subtitleLines.length * 18 + (subtitleLines.length > 0 ? 4 : 0) + 14
  const legendHeight = legendRows.length > 0 ? legendRows.length * 22 + 12 : 0
  const captionHeight = captionLines.length > 0 ? captionLines.length * 16 + 14 : 0
  const height =
    EXPORT_PADDING + headerHeight + plotHeight + legendHeight + captionHeight + EXPORT_PADDING

  const clone = source.cloneNode(true)
  if (!(clone instanceof SVGSVGElement)) {
    throw new Error("This browser cannot export the chart.")
  }
  inlineSvgPresentation(source, clone)
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
  clone.setAttribute("width", String(plotWidth))
  clone.setAttribute("height", String(plotHeight))
  clone.style.background = background
  clone.style.fontFamily = surfaceStyles.fontFamily || rootStyles.fontFamily

  const svg = new XMLSerializer().serializeToString(clone)
  const sourceUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }))
  try {
    const image = await loadImage(sourceUrl)
    const scale = Math.min(2, 4096 / width, 4096 / height)
    const canvas = document.createElement("canvas")
    canvas.width = Math.ceil(width * scale)
    canvas.height = Math.ceil(height * scale)
    const context = canvas.getContext("2d")
    if (!context) {
      throw new Error("This browser cannot export the chart.")
    }
    context.scale(scale, scale)
    context.fillStyle = background
    context.fillRect(0, 0, width, height)

    let y = EXPORT_PADDING
    context.fillStyle = foreground
    context.font = TITLE_FONT
    y = drawTextLines(context, titleLines, EXPORT_PADDING, y, 23)
    if (subtitleLines.length > 0) {
      y += 4
      context.fillStyle = muted
      context.font = BODY_FONT
      y = drawTextLines(context, subtitleLines, EXPORT_PADDING, y, 18)
    }
    y += 14
    context.drawImage(image, EXPORT_PADDING, y, plotWidth, plotHeight)
    y += plotHeight

    if (legendRows.length > 0) {
      y += 12
      context.font = BODY_FONT
      context.fillStyle = foreground
      for (const row of legendRows) {
        let x = EXPORT_PADDING
        for (const item of row) {
          context.fillStyle = item.color
          context.beginPath()
          context.arc(x + 5, y + 5, 5, 0, Math.PI * 2)
          context.fill()
          context.fillStyle = foreground
          context.fillText(item.label, x + 15, y + 9)
          x += legendItemWidth(context, item)
        }
        y += 22
      }
    }

    if (captionLines.length > 0) {
      y += 14
      context.fillStyle = muted
      context.font = CAPTION_FONT
      drawTextLines(context, captionLines, EXPORT_PADDING, y, 16)
    }

    const png = await canvasBlob(canvas)
    const downloadUrl = URL.createObjectURL(png)
    try {
      const anchor = document.createElement("a")
      anchor.download = chartPngFilename(details.title)
      anchor.href = downloadUrl
      anchor.click()
    } finally {
      URL.revokeObjectURL(downloadUrl)
    }
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

function inlineSvgPresentation(source: SVGSVGElement, clone: SVGSVGElement): void {
  const sourceElements = [source, ...source.querySelectorAll<SVGElement>("*")]
  const cloneElements = [clone, ...clone.querySelectorAll<SVGElement>("*")]
  sourceElements.forEach((sourceElement, index) => {
    const cloneElement = cloneElements[index]
    if (!cloneElement) {
      return
    }
    const styles = getComputedStyle(sourceElement)
    for (const property of SVG_PRESENTATION_PROPERTIES) {
      const value = styles.getPropertyValue(property)
      if (value) {
        cloneElement.style.setProperty(property, value)
      }
    }
  })
}

function readLegend(surface: HTMLElement): LegendItem[] {
  return [...surface.querySelectorAll<HTMLElement>(".recharts-legend-item")].flatMap((item) => {
    const label = item.textContent.trim()
    const icon = item.querySelector<SVGElement>(".recharts-legend-icon")
    if (!label || !icon) {
      return []
    }
    const styles = getComputedStyle(icon)
    const color =
      visualColor(styles.getPropertyValue("fill")) ??
      visualColor(styles.getPropertyValue("stroke")) ??
      getComputedStyle(item).color
    return [{ color, label }]
  })
}

function packLegendRows(
  context: CanvasRenderingContext2D,
  items: LegendItem[],
  maxWidth: number
): LegendItem[][] {
  const rows: LegendItem[][] = []
  let row: LegendItem[] = []
  let rowWidth = 0
  for (const item of items) {
    const itemWidth = legendItemWidth(context, item)
    if (row.length > 0 && rowWidth + itemWidth > maxWidth) {
      rows.push(row)
      row = []
      rowWidth = 0
    }
    row.push(item)
    rowWidth += itemWidth
  }
  if (row.length > 0) {
    rows.push(row)
  }
  return rows
}

function legendItemWidth(context: CanvasRenderingContext2D, item: LegendItem): number {
  return 27 + context.measureText(item.label).width
}

function wrapText(context: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.trim().split(/\s+/)
  const lines: string[] = []
  let line = ""
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line)
      line = word
    } else {
      line = candidate
    }
  }
  if (line) {
    lines.push(line)
  }
  return lines
}

function drawTextLines(
  context: CanvasRenderingContext2D,
  lines: string[],
  x: number,
  y: number,
  lineHeight: number
): number {
  for (const line of lines) {
    context.fillText(line, x, y + lineHeight)
    y += lineHeight
  }
  return y
}

function resolvedToken(styles: CSSStyleDeclaration, token: string): string | null {
  const value = styles.getPropertyValue(token).trim()
  return value || null
}

function visualColor(value: string): string | null {
  const normalized = value.trim().toLowerCase()
  return normalized && normalized !== "none" && normalized !== "transparent" ? value : null
}

function opaqueColor(value: string): string | null {
  const normalized = value.trim().toLowerCase()
  return normalized && normalized !== "transparent" && normalized !== "rgba(0, 0, 0, 0)"
    ? value
    : null
}

export function chartPngFilename(title: string): string {
  const stem = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
  return `${stem || "chart"}.png`
}

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      resolve(image)
    }
    image.onerror = () => {
      reject(new Error("The chart image could not be prepared."))
    }
    image.src = source
  })
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob)
      } else {
        reject(new Error("The chart image could not be created."))
      }
    }, "image/png")
  })
}
