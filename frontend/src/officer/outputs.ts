// Check outputs are free-form JSON objects (each worker has its own shape), typed as unknown values by the
// generated schema. These helpers read one value safely, with the expected type, or return null.

export type Outputs = { [key: string]: unknown }

export function num(outputs: Outputs | null | undefined, key: string): number | null {
  const value = outputs?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function str(outputs: Outputs | null | undefined, key: string): string | null {
  const value = outputs?.[key]
  return typeof value === 'string' ? value : null
}

export function obj(outputs: Outputs | null | undefined, key: string): Outputs | null {
  const value = outputs?.[key]
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Outputs) : null
}

export function list(outputs: Outputs | null | undefined, key: string): Outputs[] {
  const value = outputs?.[key]
  return Array.isArray(value) ? value.filter((item): item is Outputs => item !== null && typeof item === 'object') : []
}

export function fixed(value: number | null, digits = 4): string {
  return value === null ? '–' : value.toFixed(digits)
}

export function percent(value: number | null, digits = 1): string {
  return value === null ? '–' : `${(value * 100).toFixed(digits)} %`
}

/** An evidence value as short text (numbers rounded, objects as JSON). */
export function evidenceText(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)))
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return '–'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return JSON.stringify(value)
}
