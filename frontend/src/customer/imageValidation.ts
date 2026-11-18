// Client-side checks that mirror the API's rules (JPEG/PNG, <= 10 MB, >= 100 px), so the customer hears about a
// problem at once instead of after uploading. The API still checks everything again.
import { formatBytes } from '../format'

export const MAX_FILE_BYTES = 10 * 1024 * 1024
export const ACCEPTED_TYPES: readonly string[] = ['image/jpeg', 'image/png']
export const ACCEPT_ATTRIBUTE = ACCEPTED_TYPES.join(',')
export const MIN_SIDE_PX = 100 // the API refuses anything smaller
export const SHARP_DOCUMENT_PX = 1000 // below this (longest side) the small print on an ID gets hard to read

export type ImageKind = 'document' | 'selfie'

/** Problems we can see from the file itself (type, size). null = fine. */
export function fileProblem(file: { type: string; size: number }): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return 'Please choose a JPEG or PNG image.'
  if (file.size === 0) return 'This file is empty. Please choose another photo.'
  if (file.size > MAX_FILE_BYTES) return `This file is ${formatBytes(file.size)}. The limit is 10 MB.`
  return null
}

/** Problems from the image's pixel size. */
export function dimensionProblem(width: number, height: number): string | null {
  if (Math.min(width, height) < MIN_SIDE_PX) return `This image is too small (${width} × ${height} px). Please use a larger photo.`
  return null
}

/** Not an error, but worth telling the customer. */
export function dimensionWarning(width: number, height: number, kind: ImageKind): string | null {
  if (kind === 'document' && Math.max(width, height) < SHARP_DOCUMENT_PX) {
    return 'This photo is quite small, so the text on your ID may be hard to read. A sharper photo works best.'
  }
  return null
}

export function imageSize(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => reject(new Error('This file could not be opened as an image.'))
    image.src = url
  })
}

export interface CheckedImage {
  error: string | null
  warning: string | null
}

/** All checks for one picked file. */
export async function checkImage(file: Blob, url: string, kind: ImageKind): Promise<CheckedImage> {
  const problem = fileProblem(file)
  if (problem) return { error: problem, warning: null }
  try {
    const { width, height } = await imageSize(url)
    return { error: dimensionProblem(width, height), warning: dimensionWarning(width, height, kind) }
  } catch (err) {
    return { error: (err as Error).message, warning: null }
  }
}
