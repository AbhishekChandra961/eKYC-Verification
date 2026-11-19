"""Project-wide settings: paths, random seed, split ratios and data-sampling limits.

Every notebook, test and service imports these values from here, so a setting is changed in one
place only. Paths are absolute (built from this file's location), so code works no matter which
folder it is run from.
"""

from pathlib import Path

# ---------------------------------------------------------------- paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/ekyc/config.py -> project root

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # read-only: original downloads
INTERIM_DIR = DATA_DIR / "interim"  # read-only: extracted SIDTD images + annotations
PROCESSED_DIR = DATA_DIR / "processed"  # the ONLY data folder we write to

TEMPLATES_DIR = INTERIM_DIR / "templates"
CLIPS_DIR = INTERIM_DIR / "clips_cropped"

MANIFEST_FULL_CSV = PROCESSED_DIR / "manifest_full.csv"  # every image, with an in_sample flag
MANIFEST_CSV = PROCESSED_DIR / "manifest.csv"  # in_sample rows only: what models train on
FIELDS_GT_CSV = PROCESSED_DIR / "fields_ground_truth.csv"  # annotated text/photo boxes
CACHE_DIR = PROCESSED_DIR / "images"  # resized copies, mirroring data/interim's layout

REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR = PROJECT_ROOT / "models"  # gitignored weights (only the small *.json configs are in git)

# ---------------------------------------------------------------- dataset facts
# The 10 SIDTD document types. Filenames are parsed against this list (not by splitting on "_"),
# because every type name itself contains an underscore, e.g. "rus_internalpassport".
DOC_TYPES = (
    "alb_id",
    "aze_passport",
    "esp_id",
    "est_id",
    "fin_id",
    "grc_passport",
    "lva_passport",
    "rus_internalpassport",
    "srb_passport",
    "svk_id",
)

# ---------------------------------------------------------------- reproducibility + splits
SEED = 42
SPLIT_RATIOS = {"train": 0.70, "val": 0.15, "test": 0.15}

# ---------------------------------------------------------------- sampling + image cache
# Clip frames of one document are near-duplicates (a video of the same card), so we keep only a
# few evenly spaced frames per document. Fakes get more frames because there are fewer of them.
MAX_REAL_FRAMES = 8
MAX_FAKE_FRAMES = 20

RESIZE_LONGEST = 512  # cached images: longest side in pixels (aspect ratio kept)
JPEG_QUALITY = 92  # cached images: JPEG quality

# ---------------------------------------------------------------- blank video frames (Phase 2.1)
# Some clip frames show no document: the dataset's automatic crop missed the card and left a black
# or plain-coloured frame. A frame is "empty" if its 64x40 greyscale thumbnail is (almost) one flat
# colour (std < 3 grey levels) or more than 90 % of its pixels are near-black (grey value < 20).
# Calibrated by inspecting every flagged frame and the closest unflagged ones (notebook 01).
BLANK_THUMBNAIL = (64, 40)
BLANK_STD_MAX = 3.0
BLANK_DARK_LEVEL = 20
BLANK_DARK_SHARE_MIN = 0.9

# ---------------------------------------------------------------- forgery v2: hi-res templates + tiles (Phase 3B v2)
# v1 found two shortcuts: forged clip frames differ from genuine ones in recording and file format, and
# forged templates were saved at JPEG quality 75 against 92 for genuine ones. v2 therefore uses templates
# only, and every template (both classes) goes through the same code path: RGB, longest side resized to
# exactly 1280 px (small cards are enlarged too, which also breaks the alignment of the old 8x8 JPEG
# blocks), then saved at JPEG quality 75.
HIRES_DIR = PROCESSED_DIR / "hires_q75"
HIRES_MANIFEST_CSV = HIRES_DIR / "pages.csv"  # one row per template page, with edit boxes in hi-res px
HIRES_LONGEST = 1280
HIRES_QUALITY = 75
TILE_SIZE = 224  # tiles cut from the hi-res pages, EfficientNetB0's native input size
TILE_STRIDE = 112  # half a tile: neighbouring tiles overlap by 50 %

# ---------------------------------------------------------------- forgery v3: equal compression HISTORY (Phase 3B v3)
# v2 found a weaker residual cue: forged templates had been saved at JPEG quality 75 at their ORIGINAL size,
# genuine ones at 92. On cards that are enlarged to 1280 px (est_id, fin_id, svk_id, grc_passport) the old 8x8
# block pattern is stretched rather than erased and survives the final save. v3 gives every GENUINE page the
# forged pages' history first: a quality-75 save at its original size, then the usual resize + quality-75 save.
# Forged pages are processed exactly as in v2. hires_q75 (v2) is kept for comparison.
HIRES_EQ_DIR = PROCESSED_DIR / "hires_q75_eq"
HIRES_EQ_MANIFEST_CSV = HIRES_EQ_DIR / "pages.csv"
GENUINE_PRE_QUALITY = 75  # the quality the forged originals were saved at

# ---------------------------------------------------------------- face verification (Phase 4)
# Production path: OpenCV's YuNet detector + SFace recognizer, ONNX files from github.com/opencv/opencv_zoo
# (YuNet: MIT licence, SFace: Apache 2.0; licence files next to the models). Showcase: a Keras Siamese network.
LFW_DIR = RAW_DIR / "lfw"  # sklearn's data_home: lfw_home/ with the images and pairsDev{Train,Test}.txt (read-only)
FACE_MODEL_DIR = MODELS_DIR / "face"
YUNET_ONNX = FACE_MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_ONNX = FACE_MODEL_DIR / "face_recognition_sface_2021dec.onnx"
FACE_MAX_FAR = 0.01  # thresholds allow at most 1 % false accepts: accepting an impostor is the costly KYC error

# ---------------------------------------------------------------- model weights release (Phase 10)
# The trained models are ONE GitHub release asset (models/ is gitignored). scripts/build_model_release.py builds the
# zip, scripts/download_models.py downloads it, checks the SHA-256 below and every file's line in the zip's
# SHA256SUMS, and unpacks it into models/. A new release = a new version, file name and SHA-256 here.
MODEL_RELEASE_VERSION = "v1.0.0"
MODEL_RELEASE_FILE = "ekyc-models-v1.0.zip"
MODEL_RELEASE_URL = (
    "https://github.com/AbhishekChandra961/eKYC-Verification/releases/download/"
    f"{MODEL_RELEASE_VERSION}/{MODEL_RELEASE_FILE}"
)
MODEL_RELEASE_SHA256 = "2d7fa258d41681553429245b60fc7eb3fe59e58887aa6c0cea0aba398959b1fc"
MODEL_RELEASE_FILES = (  # paths inside models/ (and inside the zip)
    "doc_classifier.keras",
    "doc_classifier.json",
    "forgery_detector.keras",  # v3, the accepted model
    "forgery_detector.json",
    "face_config.json",
    "face_siamese.keras",  # showcase only, never used by the pipeline
    "face/face_detection_yunet_2023mar.onnx",
    "face/LICENSE_yunet_MIT.txt",
    "face/face_recognition_sface_2021dec.onnx",
    "face/LICENSE_sface_Apache-2.0.txt",
)
