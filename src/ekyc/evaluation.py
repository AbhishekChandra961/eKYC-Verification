"""Evaluation helpers for binary classifiers (genuine = 0 / forged = 1).

Convention everywhere: an image is predicted "forged" when score >= threshold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from ekyc.tiles import page_scores


def ranking_scores(y_true, scores) -> dict:
    """Threshold-free metrics. PR-AUC is reported as average precision (the area under the
    precision-recall curve, computed as a step function); a random model scores the forged share."""
    return {"pr_auc": float(average_precision_score(y_true, scores)),
            "roc_auc": float(roc_auc_score(y_true, scores))}


def threshold_for_recall(y_true, scores, min_recall: float = 0.90) -> dict:
    """Highest threshold whose forged-recall is still >= min_recall (= the best precision among
    thresholds that catch at least min_recall of the forgeries)."""
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    ok = np.where(recall[:-1] >= min_recall)[0]  # thresholds ascend, so recall descends
    i = ok.max()
    return {"threshold": float(thresholds[i]), "precision": float(precision[i]), "recall": float(recall[i])}


def f1_optimal_threshold(y_true, scores) -> dict:
    """Threshold with the highest F1 score (harmonic mean of precision and recall)."""
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    p, r = precision[:-1], recall[:-1]
    f1 = np.divide(2 * p * r, p + r, out=np.zeros_like(p), where=(p + r) > 0)
    i = int(np.argmax(f1))
    return {"threshold": float(thresholds[i]), "precision": float(p[i]), "recall": float(r[i]), "f1": float(f1[i])}


def confusion_at(y_true, scores, threshold: float) -> pd.DataFrame:
    """2x2 confusion matrix (rows = truth, columns = prediction) at a threshold."""
    y_true = np.asarray(y_true)
    predicted = (np.asarray(scores) >= threshold).astype(int)
    table = pd.crosstab(pd.Series(y_true, name="true"), pd.Series(predicted, name="predicted"))
    table = table.reindex(index=[0, 1], columns=[0, 1], fill_value=0)
    table.index = ["genuine", "forged"]
    table.columns = ["predicted genuine", "predicted forged"]
    return table


def breakdown(df: pd.DataFrame, by: str, threshold: float) -> pd.DataFrame:
    """Per-group results at a threshold. `df` needs columns label (0/1), score and `by`.
    recall = share of forged images caught; false_alarm = share of genuine images flagged as forged;
    pr_auc only where a group has both classes."""
    rows = {}
    for group, part in df.groupby(by, dropna=True):
        forged, genuine = part[part["label"] == 1], part[part["label"] == 0]
        flagged = part["score"] >= threshold
        rows[group] = {
            "images": len(part),
            "forged": len(forged),
            "recall": (forged["score"] >= threshold).mean() if len(forged) else np.nan,
            "false_alarm": (genuine["score"] >= threshold).mean() if len(genuine) else np.nan,
            "precision": part.loc[flagged, "label"].mean() if flagged.any() else np.nan,
            "pr_auc": average_precision_score(part["label"], part["score"]) if part["label"].nunique() == 2 else np.nan,
        }
    return pd.DataFrame(rows).T.rename_axis(by)


# =============================================================== shortcut checks for tile models (Phase 3B v2/v3)
# A forgery model can score well for the wrong reason: it may recognise forged PAGES (their file history,
# scanner, colours) instead of the edit. These checks look at the parts of forged pages that do NOT show the
# edit. If the model can still tell those apart from genuine pages, it has learned a page-level shortcut.
# Tile tables come from tiles.build_tile_table (columns page, x, y, label, far_from_edit, plus a score column);
# `pages` is the matching pages table (row i = page i), with label and doc_type.


def matched_auc(scores, is_test, strata) -> float:
    """AUC of 'test' items against 'reference' items, comparing only items of the same stratum.

    Within one stratum the Mann-Whitney U statistic counts, over all (test, reference) pairs, how often the
    test item scores higher (a tie counts 1/2); U / (n_test * n_reference) is that stratum's ROC-AUC. Here U and
    the pair counts are summed over all strata, so the result is the probability that a test item beats a
    reference item FROM THE SAME STRATUM. 0.5 = no difference.
    Why strata: tiles at different places of a page score differently (text areas higher than plain
    background). If test tiles come from other places than reference tiles, an unmatched AUC compares places,
    not pages: the blind spot of v2's plain negative control.
    """
    df = pd.DataFrame({"score": np.asarray(scores, dtype=float), "test": np.asarray(is_test, dtype=bool),
                       "stratum": np.asarray(strata)})
    df["rank"] = df.groupby("stratum")["score"].rank(method="average")  # tied scores share their mean rank
    df["test_rank"] = df["rank"].where(df["test"], 0.0)
    per = df.groupby("stratum").agg(n=("test", "size"), n_test=("test", "sum"), rank_sum=("test_rank", "sum"))
    pairs = per["n_test"] * (per["n"] - per["n_test"])
    u = per["rank_sum"] - per["n_test"] * (per["n_test"] + 1) / 2  # 0 in strata with only one kind of item
    return float(u.sum() / pairs.sum()) if pairs.sum() > 0 else float("nan")


def page_bootstrap_ci(table: pd.DataFrame, statistic, n_boot: int = 200, seed: int = 0,
                      level: float = 0.95) -> tuple[float, float]:
    """Percentile confidence interval of statistic(table), resampling PAGES with replacement, separately for
    genuine and forged pages (so both counts stay the same). All tiles of a drawn page come along: tiles of
    one page share its printing and file history, so they are not independent pieces of evidence.
    `table` needs the columns page and page_label (0/1)."""
    rng = np.random.default_rng(seed)
    rows_of = table.groupby("page").indices  # page -> row positions in `table`
    classes = [table.loc[table["page_label"] == c, "page"].unique() for c in (0, 1)]
    values = []
    for _ in range(n_boot):
        drawn = np.concatenate([rng.choice(pages, len(pages)) for pages in classes if len(pages)])
        values.append(statistic(table.iloc[np.concatenate([rows_of[p] for p in drawn])]))
    low, high = np.nanquantile(values, [(1 - level) / 2, (1 + level) / 2])
    return float(low), float(high)


def _off_edit_vs_genuine(tiles: pd.DataFrame, pages: pd.DataFrame, score_column: str,
                         far_only: bool = False) -> pd.DataFrame:
    """All tiles of genuine pages + the tiles of forged pages that do not show the edit (label 0; with
    far_only also >= 112 px from it), with page_label, doc_type and a position stratum (doc_type, x, y).
    All pages of one document type have the same hi-res size, so (doc_type, x, y) is the same place."""
    t = tiles[["page", "x", "y", "label", "far_from_edit", score_column]].copy()
    t["page_label"] = pages["label"].to_numpy()[t["page"].to_numpy()]
    t["doc_type"] = pages["doc_type"].to_numpy()[t["page"].to_numpy()]
    off_edit = (t["page_label"] == 1) & (t["label"] == 0)
    if far_only:
        off_edit &= t["far_from_edit"].astype(bool)
    t = t[(t["page_label"] == 0) | off_edit]
    return t.assign(stratum=t.groupby(["doc_type", "x", "y"]).ngroup())


def position_matched_control(tiles: pd.DataFrame, pages: pd.DataFrame, score_column: str = "score",
                             far_only: bool = False, n_boot: int = 200, seed: int = 0) -> pd.DataFrame:
    """Position-matched negative control: the standard shortcut test for every forgery model (Phase 3B v2).

    Compares the tiles of FORGED pages that do not show the edit with the tiles of GENUINE pages at the same
    position of the same document type (matched_auc).
    - about 0.5: away from the edit, forged pages look like genuine ones to the model (good);
    - clearly above 0.5: the model recognises forged pages by something other than the edit (a shortcut).
    Returns one row for all document types together and one per type: tile counts, AUC and a 95 % interval
    from page_bootstrap_ci.
    """
    t = _off_edit_vs_genuine(tiles, pages, score_column, far_only)

    def auc(part):
        return matched_auc(part[score_column], part["page_label"] == 1, part["stratum"])

    rows = {}
    for name, part in [("all types", t), *t.groupby("doc_type")]:
        low, high = page_bootstrap_ci(part, auc, n_boot, seed)
        rows[name] = {"forged-page tiles": int((part["page_label"] == 1).sum()),
                      "genuine tiles": int((part["page_label"] == 0).sum()),
                      "AUC": auc(part), "95% low": low, "95% high": high}
    return pd.DataFrame.from_dict(rows, orient="index")


def edit_hidden_doc_auc(tiles: pd.DataFrame, pages: pd.DataFrame, how: str = "top3",
                        score_column: str = "score") -> float:
    """Document ROC-AUC when forged pages are judged WITHOUT their edit: a forged page keeps only its label-0
    tiles (no edit tiles, no slivers), a genuine page keeps all its tiles.
    If the page score comes from the edit, forged pages now look genuine and the AUC falls to about 0.5
    (a little below for a model with no shortcut: forged pages keep ~10 % fewer tiles, so their top tiles are
    slightly lower). Clearly above 0.5 = forged pages are recognised without their edit."""
    y = pages["label"].to_numpy()
    kept = tiles[(y[tiles["page"].to_numpy()] == 0) | (tiles["label"] == 0).to_numpy()]
    doc = page_scores(kept, score_column, how).reindex(range(len(pages))).fillna(0.0)  # no tile left: clean
    return float(roc_auc_score(y, doc))


def compression_history_check(tiles: pd.DataFrame, pages: pd.DataFrame, other_genuine_scores, threshold: float,
                              how: str = "top3", score_column: str = "score",
                              names: tuple[str, str] = ("as cached", "genuine re-saved")) -> pd.DataFrame:
    """Round-trip check (Phase 3B v2): does the model's verdict depend on a page's compression HISTORY?

    `other_genuine_scores` (aligned with `tiles`; only genuine pages' entries are used) are the tile scores of
    the SAME genuine pages stored with a different history, e.g. with or without the forged pages' extra JPEG
    save at original size. Forged pages keep their scores. Each column reports the position-matched control
    (without interval), the edit-hidden document AUC, document ROC-AUC and PR-AUC, false alarms at
    `threshold` and the mean genuine tile score. A model that ignores compression history gives about the
    same numbers in both columns (v2 did not: its false alarms doubled).
    """
    y = pages["label"].to_numpy()
    genuine_tile = y[tiles["page"].to_numpy()] == 0
    swapped = tiles.copy()
    swapped.loc[genuine_tile, score_column] = np.asarray(other_genuine_scores, dtype=float)[genuine_tile]
    columns = {}
    for name, table in zip(names, (tiles, swapped)):
        doc = page_scores(table, score_column, how).reindex(range(len(pages))).to_numpy()
        control = _off_edit_vs_genuine(table, pages, score_column)
        ranking = ranking_scores(y, doc)
        columns[name] = {
            "position-matched control AUC": matched_auc(control[score_column], control["page_label"] == 1,
                                                        control["stratum"]),
            "edit-hidden document ROC-AUC": edit_hidden_doc_auc(table, pages, how, score_column),
            "document ROC-AUC": ranking["roc_auc"],
            "document PR-AUC": ranking["pr_auc"],
            "false alarms at threshold": int((doc[y == 0] >= threshold).sum()),
            "genuine pages": int((y == 0).sum()),
            "mean genuine tile score": float(table.loc[genuine_tile, score_column].mean()),
        }
    return pd.DataFrame(columns)
