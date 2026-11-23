# Fake-camera frames for the demo site's Playwright tests (Phase 13)

`neutral.jpg`, `left.jpg`, `right.jpg` (640 x 480): the genuine_1 demo selfie (a simulated selfie of the generated
portrait on SIDTD document srb_passport_16, TEST split) on a grey background, looking at the camera and with the head
turned left and right. The turns are SYNTHETIC: `ekyc.liveness_sim.synthetic_head_turn` (+-35 degrees), made by
`scripts/make_demo_samples.py`. No real person. `e2e-demo/fakeCamera.ts` loops them as a Motion-JPEG video for
Chromium's fake webcam.

Derived from SIDTD (Boned et al., *Scientific Data* 2024; built on MIDV-2020), licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), like the demo site's other sample images.
