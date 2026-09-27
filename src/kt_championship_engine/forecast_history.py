from __future__ import annotations

import csv
import json
from pathlib import Path

from .schemas import GameForecast


def merge_forecast_history(path: Path, current: list[GameForecast]) -> list[GameForecast]:
    history: dict[tuple[str, str], GameForecast] = {}
    current_game_ids = {forecast.game_id for forecast in current}
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                forecast = GameForecast.model_validate(_normalize_row(row))
                if forecast.is_remaining and forecast.game_id not in current_game_ids:
                    continue
                history[(forecast.game_id, forecast.team)] = forecast
    for forecast in current:
        key = (forecast.game_id, forecast.team)
        previous = history.get(key)
        if previous is not None and forecast.actual_result is not None:
            values = previous.model_dump()
            values.update(
                {
                    "game_date": forecast.game_date,
                    "estimated_game_date": forecast.estimated_game_date,
                    "is_remaining": False,
                    "actual_result": forecast.actual_result,
                    "result_source": forecast.result_source,
                }
            )
            history[key] = GameForecast.model_validate(values)
        else:
            history[key] = forecast
    return sorted(history.values(), key=lambda row: (row.game_date is None, row.game_date, row.game_id, row.team))


def _normalize_row(row: dict[str, str]) -> dict[str, object]:
    normalized: dict[str, object] = dict(row)
    nullable_fields = {
        "base_probability",
        "jev_probability",
        "combined_probability",
        "game_date",
        "estimated_game_date",
        "jev_http_status",
        "jev_reason_code",
        "jev_confidence",
        "jev_message",
        "jev_request_hash",
        "jev_model",
        "effective_base_weight",
        "effective_jev_weight",
        "actual_result",
        "result_source",
        "predicted_at",
    }
    for field in nullable_fields:
        if normalized.get(field) == "":
            normalized[field] = None
    components = normalized.get("jev_components")
    if isinstance(components, str):
        normalized["jev_components"] = json.loads(components) if components else {}
    return normalized
