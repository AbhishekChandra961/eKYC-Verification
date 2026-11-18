// Turning getUserMedia errors into a reason the customer can act on.

export type CameraProblem = 'denied' | 'unavailable' | 'failed'

/** Why the camera could not start, in the customer's words. */
export function cameraProblem(error: unknown): { kind: CameraProblem; message: string } {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return { kind: 'denied', message: 'Camera access was not allowed. You can allow it in your browser settings, or upload a selfie photo instead.' }
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'NotSupportedError') {
    return { kind: 'unavailable', message: 'No camera was found on this device. Please upload a selfie photo instead.' }
  }
  if (name === 'NotReadableError' || name === 'AbortError') {
    return { kind: 'failed', message: 'The camera is busy (another app may be using it). Close that app and try again, or upload a photo.' }
  }
  return { kind: 'failed', message: 'The camera could not be started. Please upload a selfie photo instead.' }
}
