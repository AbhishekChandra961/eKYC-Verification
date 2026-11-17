"""Page scores of the accepted forgery model (Phase 3B v3) for the validation and test template pages.

Phase 5 uses them to ask: which forgeries does the pixel model miss (score < 0.729), and do the consistency rules
catch those? The model is frozen; nothing is tuned on these scores. Runs as its own process (notebook 05 calls
it with subprocess), so TensorFlow's memory is released before the vision LLM runs.

usage: .venv/bin/python scripts/score_forgery_pages.py [OUT.csv]
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import keras  # noqa: E402
import pandas as pd  # noqa: E402

from ekyc import config, tiles  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else config.REPORTS_DIR / "phase5" / "forgery_v3_page_scores_valtest.csv"

pages = pd.read_csv(config.HIRES_EQ_MANIFEST_CSV)  # 1280 px pages, the forgery model's input (Phase 3B v3)
pages = pages[pages["split"].isin(["val", "test"])].reset_index(drop=True)
model = keras.models.load_model(config.PROJECT_ROOT / "models" / "forgery_detector.keras")
tile_table = tiles.build_tile_table(pages)
tile_table["score"] = tiles.score_tiles(model, pages, tile_table)
pages["forgery_score"] = tiles.page_scores(tile_table, how="max").reindex(range(len(pages))).to_numpy()  # highest tile
OUT.parent.mkdir(parents=True, exist_ok=True)
pages[["doc_id", "fake_name", "split", "label", "doc_type", "ctype", "altered_field", "image_path",
       "forgery_score"]].to_csv(OUT, index=False)
print(f"scored {len(pages)} pages ({len(tile_table):,} tiles) -> {OUT}")
