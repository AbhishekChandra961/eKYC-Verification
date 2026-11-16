"""Evaluation helpers for binary classifiers (genuine = 0 / forged = 1).

Convention everywhere: an image is predicted "forged" when score >= threshold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


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
