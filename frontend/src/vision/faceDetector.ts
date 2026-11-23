// The in-browser face detector (Phase 13): MediaPipe Tasks' FaceDetector with the BlazeFace short-range model.
// Every file comes from this site: the WebAssembly runtime is copied by Vite from node_modules (`?url` imports emit
// it as an asset), the model is bundled from src/vision/models/ (see its README). No CDN, nothing uploaded.
// Loaded on demand (dynamic import) only when the camera starts, so other pages never download it. A model wrapper,
// not a screen: the customer's camera (customer/WebcamCapture.tsx) uses it only for guidance.
import wasmLoaderUrl from '@mediapipe/tasks-vision/vision_wasm_internal.js?url'
import wasmBinaryUrl from '@mediapipe/tasks-vision/vision_wasm_internal.wasm?url'
import modelUrl from './models/blaze_face_short_range.tflite?url'
import type { DetectedFace } from '../customer/selfieGuidance'

export interface FaceFinder {
  /** Faces in the video's current frame, in pixels of the unmirrored image. Timestamps must increase. */
  find(video: HTMLVideoElement, timestampMs: number): DetectedFace[]
  close(): void
}

const absolute = (url: string) => new URL(url, window.location.href).href

// MediaPipe Tasks (1.2.x) always creates a usage logger that POSTs anonymous statistics (task type, running mode,
// timings; no images) to Google every 60 s and when a task closes. The library has no switch for it, but this camera
// promises that nothing leaves the browser (and the real app sends nothing to third parties), so requests to that one
// host are answered here, locally, with an error: the logger then stops (it gives up after a failed send). Found by the
// demo site's Playwright test, which fails on any request that leaves the site.
const MEDIAPIPE_LOGGING = 'https://odml.pa.googleapis.com/'
let loggingBlocked = false

function blockMediaPipeLogging() {
  if (loggingBlocked) return
  loggingBlocked = true
  const realFetch = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.startsWith(MEDIAPIPE_LOGGING)) return Promise.resolve(new Response(null, { status: 403 }))
    return realFetch(input, init)
  }
}

export async function loadFaceFinder(): Promise<FaceFinder> {
  blockMediaPipeLogging()
  const { FaceDetector } = await import('@mediapipe/tasks-vision')
  const detector = await FaceDetector.createFromOptions(
    { wasmLoaderPath: absolute(wasmLoaderUrl), wasmBinaryPath: absolute(wasmBinaryUrl) },
    {
      baseOptions: { modelAssetPath: absolute(modelUrl), delegate: 'CPU' }, // CPU: works without a GPU (and headless)
      runningMode: 'VIDEO',
      minDetectionConfidence: 0.6,
    },
  )
  return {
    find(video, timestampMs) {
      const width = video.videoWidth
      const height = video.videoHeight
      return detector.detectForVideo(video, timestampMs).detections.flatMap((d) => d.boundingBox ? [{
        box: { x: d.boundingBox.originX, y: d.boundingBox.originY, width: d.boundingBox.width, height: d.boundingBox.height },
        keypoints: d.keypoints.map((k) => ({ x: k.x * width, y: k.y * height })), // normalised 0-1 -> pixels
      }] : [])
    },
    close() {
      detector.close()
    },
  }
}
