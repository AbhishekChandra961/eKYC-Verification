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
