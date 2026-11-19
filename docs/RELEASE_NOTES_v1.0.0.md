# eKYC Verification v1.0.0

The final capstone release: a digital KYC pipeline with four AI checks (document type, forgery with a heatmap, face
match, and local vision-LLM field extraction with MRZ rules), an explainable decision engine, and Kafka
microservices with a React frontend. See the [README](https://github.com/AbhishekChandra961/eKYC-Verification#readme)
and the [project report](https://github.com/AbhishekChandra961/eKYC-Verification/blob/main/docs/report/REPORT.md).

## Asset: `ekyc-models-v1.0.zip` (99.7 MB)

SHA-256 `2d7fa258d41681553429245b60fc7eb3fe59e58887aa6c0cea0aba398959b1fc` (also in `src/ekyc/config.py`).

```bash
.venv/bin/python scripts/download_models.py   # download, check the zip and every file, unpack into models/
```

| File | What | Licence |
|---|---|---|
| `doc_classifier.keras` + `.json` | Document type classifier, EfficientNetB0 (frozen) + head, 224 px; test accuracy 99.29 % | trained here (EfficientNet weights: Apache 2.0) |
| `forgery_detector.keras` + `.json` | Forgery detector v3, tiles of 1280 px pages; test ROC-AUC 0.976, PR-AUC 0.984 | trained here |
| `face/face_detection_yunet_2023mar.onnx` + licence | YuNet face detector (OpenCV Zoo) | MIT |
| `face/face_recognition_sface_2021dec.onnx` + licence | SFace face recognizer (OpenCV Zoo); LFW test ROC-AUC 0.997 | Apache 2.0 |
| `face_config.json` | Face thresholds (0.2597 mismatch, 0.556 review) | – |
| `face_siamese.keras` | Siamese network trained on LFW: a showcase, not used by the pipeline | trained here |
| `README.txt`, `SHA256SUMS` | What each file is; one checksum per file | – |

**Not included:**
- the rejected comparison models of the shortcut-learning study: `forgery_detector_v1_confounded` (whole-image,
  learned recording style and JPEG quality) and `forgery_detector_v2_compression_cue` (residual compression-history
  cue). Their JSON configs stay in the repository as the record;
- the training checkpoints.

**Intended use:**
- research and education only;
- trained and evaluated on synthetic SIDTD documents (based on MIDV-2020) and LFW;
- not validated on real identity documents or real selfie-ID pairs;
- not for real KYC decisions.
