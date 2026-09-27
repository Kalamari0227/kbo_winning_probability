from __future__ import annotations

import math
from collections.abc import Iterable

from .schemas import GameForecast


def brier_scores(predictions: Iterable[GameForecast]) -> dict[str, float]:
    rows = [prediction for prediction in predictions if prediction.actual_result is not None]
    if not rows:
        raise ValueError("no scored predictions")

    scores: dict[str, float] = {}
    for model_name, attribute in (
        ("base", "base_probability"),
        ("jev", "jev_probability"),
        ("combined", "combined_probability"),
    ):
        values = []
        for row in rows:
            if model_name == "jev" and row.jev_status.value != "ok":
                continue
            probability = getattr(row, attribute)
            if probability is None:
                continue
            actual = {"win": 1.0, "loss": 0.0, "tie": 0.5}[row.actual_result]
            values.append((probability - actual) ** 2)
        scores[model_name] = sum(values) / len(values) if values else math.nan
        scores[f"{model_name}_count"] = len(values)
    return scores
