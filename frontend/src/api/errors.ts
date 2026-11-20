// Errors shared by the real API client (client.ts) and the demo client (../demo/client.ts). Kept in their own module so
// the two clients do not import each other.

/** Every failed call throws this. status 0 = the server could not be reached. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** A request cancelled by its AbortController (checked by name: not every runtime's DOMException is an Error). */
export function isAbort(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError'
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
