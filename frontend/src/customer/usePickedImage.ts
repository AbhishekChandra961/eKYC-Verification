import { useCallback, useEffect, useRef, useState } from 'react'
import { checkImage, type ImageKind } from './imageValidation'

export interface PickedImage {
  blob: Blob
  url: string // object URL for the preview (freed when replaced or when the wizard closes)
  name: string
  error: string | null
  warning: string | null
}

/** One chosen image (file, camera capture) with its preview URL and validation result. */
export function usePickedImage(kind: ImageKind) {
  const [picked, setPicked] = useState<PickedImage | null>(null)
  const current = useRef<PickedImage | null>(null)

  const replace = useCallback((next: PickedImage | null) => {
    if (current.current) URL.revokeObjectURL(current.current.url)
    current.current = next
    setPicked(next)
  }, [])

  const pick = useCallback(async (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob)
    const checked = await checkImage(blob, url, kind)
    replace({ blob, url, name, ...checked })
  }, [kind, replace])

  const clear = useCallback(() => replace(null), [replace])

  useEffect(() => () => {
    if (current.current) URL.revokeObjectURL(current.current.url)
  }, [])

  return { picked, pick, clear }
}
