# In-browser face detector (Phase 13)

`blaze_face_short_range.tflite`: MediaPipe's BlazeFace short-range face detector (float16), for faces within about
2 m of a front camera. It finds faces and 6 keypoints (eyes, nose tip, mouth, ears), which the smart selfie camera
uses for its guidance ("move closer", "centre your face") and its head-turn prompts.

- Source: `https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite`
  (Google AI Edge model card: *BlazeFace (Short Range)*). Downloaded on 23 Nov 2026.
- Size: 229,746 bytes. SHA-256 `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f`.
- Licence: Apache 2.0, like the MediaPipe Tasks runtime (`@mediapipe/tasks-vision`, whose WebAssembly files Vite
  copies from `node_modules` at build time).

It is bundled with the app (imported with `?url`, so Vite serves it from the site itself): the browser never loads a
model or runtime from a third-party CDN. Nothing it computes is sent to the server: the server checks the head-turn
frames itself (`src/ekyc/liveness.py`).

Used by `src/vision/faceDetector.ts`; the guidance logic is `src/customer/selfieGuidance.ts`.
