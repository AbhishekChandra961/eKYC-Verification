// Number and text formatting for the dashboards.

/** 0.32667 -> "32.7%" ("–" when there is nothing to divide). */
export function percent(rate: number | null, digits = 1): string {
  return rate === null ? '–' : `${(rate * 100).toFixed(digits)}%`
}

/** 77.15 -> "77.2 s" */
export function seconds(value: number | null, digits = 1): string {
  return value === null ? '–' : `${value.toFixed(digits)} s`
}

/** A model metric as stored in reports/ (up to 4 decimals, no rounding beyond that). */
export function metricValue(value: number | null): string {
  return value === null ? '–' : String(Number(value.toFixed(4)))
}

/** "2026-11-18T09:36:12Z" -> "18 Nov 2026, 09:36 UTC" (always UTC: the same for every visitor). */
export function formatDataAsOf(iso: string): string {
  const text = new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC',
  }).format(new Date(iso))
  return `${text} UTC`
}

/** Breaks a long axis label into lines of at most `width` characters, at spaces (the chart draws "\n" as a line
 *  break). A single word longer than `width` stays whole. */
export function wrapLabel(text: string, width: number): string {
  const lines: string[] = []
  let line = ''
  for (const word of text.split(' ')) {
    if (line && `${line} ${word}`.length > width) {
      lines.push(line)
      line = word
    } else {
      line = line ? `${line} ${word}` : word
    }
  }
  if (line) lines.push(line)
  return lines.join('\n')
}
