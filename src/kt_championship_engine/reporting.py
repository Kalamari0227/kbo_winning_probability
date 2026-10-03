from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import EngineConfig
from .forecast_history import merge_forecast_history
from .schemas import DataManifest, GameForecast, JevStatus
from .simulation import MagicNumber, SimulationResult, date_confirmation_probabilities

TEAM_LABELS = {"SS": "삼성(SS)"}


@dataclass(frozen=True)
class RunArtifacts:
    summary_md: Path
    summary_json: Path
    game_forecasts_csv: Path
    date_confirmation_csv: Path
    final_wins_distribution_csv: Path
    final_rank_distribution_csv: Path
    data_manifest_json: Path


def write_run_artifacts(
    result: SimulationResult,
    forecasts: list[GameForecast],
    manifest: DataManifest,
    output_dir: Path,
    config: EngineConfig | None = None,
    magic_number: MagicNumber | None = None,
) -> RunArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(result, forecasts, manifest, config, magic_number)

    summary_json = output_dir / "summary.json"
    summary_content = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    summary_json.write_text(summary_content, encoding="utf-8")
    (output_dir / "simulation_summary.json").write_text(summary_content, encoding="utf-8")

    summary_md = output_dir / "summary.md"
    summary_md.write_text(_markdown_summary(summary), encoding="utf-8")

    game_forecasts_csv = output_dir / "game_forecasts.csv"
    _write_forecasts(game_forecasts_csv, merge_forecast_history(game_forecasts_csv, forecasts))

    date_confirmation_csv = output_dir / "date_confirmation.csv"
    _write_date_confirmation(date_confirmation_csv, result)

    final_wins_distribution_csv = output_dir / "final_wins_distribution.csv"
    _write_win_distribution(final_wins_distribution_csv, result)

    final_rank_distribution_csv = output_dir / "final_rank_distribution.csv"
    _write_rank_distribution(final_rank_distribution_csv, result)

    data_manifest_json = output_dir / "data_manifest.json"
    data_manifest_json.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return RunArtifacts(
        summary_md=summary_md,
        summary_json=summary_json,
        game_forecasts_csv=game_forecasts_csv,
        date_confirmation_csv=date_confirmation_csv,
        final_wins_distribution_csv=final_wins_distribution_csv,
        final_rank_distribution_csv=final_rank_distribution_csv,
        data_manifest_json=data_manifest_json,
    )


def _summary(
    result: SimulationResult,
    forecasts: list[GameForecast],
    manifest: DataManifest,
    config: EngineConfig | None,
    magic_number: MagicNumber | None,
) -> dict[str, object]:
    win_stats: dict[str, dict[str, float]] = {}
    for team in sorted(result.team_win_totals):
        values = result.team_win_totals[team]
        win_stats[team] = {
            "mean": float(np.mean(values)),
            "p05": float(np.percentile(values, 5)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
        }
    risk_games = sorted(
        (
            {
                "game_id": forecast.game_id,
                "team": forecast.team,
                "opponent": forecast.opponent,
                "combined_probability": forecast.combined_probability,
                "risk_distance": abs((forecast.combined_probability or 0.5) - 0.5),
            }
            for forecast in forecasts
            if forecast.combined_probability is not None
            and ({forecast.team, forecast.opponent} & {"KT", "SS"})
        ),
        key=lambda item: item["risk_distance"],
    )[:5]
    configured_base_weight = config.base_weight if config else 0.60
    configured_jev_weight = config.jev_weight if config else 0.40
    effective_base_values = [
        forecast.effective_base_weight for forecast in forecasts if forecast.effective_base_weight is not None
    ]
    effective_jev_values = [
        forecast.effective_jev_weight for forecast in forecasts if forecast.effective_jev_weight is not None
    ]
    effective_base_weight = float(np.mean(effective_base_values)) if effective_base_values else configured_base_weight
    effective_jev_weight = float(np.mean(effective_jev_values)) if effective_jev_values else configured_jev_weight
    remaining_forecasts = [forecast for forecast in forecasts if forecast.is_remaining]
    jev_status_counts = dict(Counter(forecast.jev_status.value for forecast in remaining_forecasts))
    jev_successful_game_count = sum(
        forecast.jev_status is JevStatus.OK and forecast.jev_call_attempted for forecast in remaining_forecasts
    )
    jev_failed_call_count = sum(
        forecast.jev_call_attempted and forecast.jev_status is not JevStatus.OK for forecast in remaining_forecasts
    )
    base_only_game_count = sum(forecast.jev_probability is None for forecast in remaining_forecasts)
    forecast_mode = (
        "base_only"
        if jev_successful_game_count == 0
        else "jev_adjusted"
        if base_only_game_count == 0
        else "mixed_base_jev"
    )
    preflight = next((forecast for forecast in remaining_forecasts if forecast.jev_is_preflight), None)
    if preflight is None:
        jev_preflight_display = "비활성화" if remaining_forecasts else "잔여 경기 없음"
    elif preflight.jev_status is JevStatus.OK:
        jev_preflight_display = f"성공 (HTTP {preflight.jev_http_status})"
    elif preflight.jev_reason_code == "missing_api_key":
        jev_preflight_display = "미수행 (TYPESAFE_API_KEY 없음)"
    elif not preflight.jev_call_attempted:
        jev_preflight_display = f"미수행 ({preflight.jev_reason_code or preflight.jev_status.value})"
    else:
        jev_preflight_display = f"실패 ({preflight.jev_status.value})"
    feature_quality_counts = dict(Counter(forecast.feature_quality for forecast in forecasts))
    official_count = manifest.official_record_count or 0
    estimated_count = manifest.estimated_record_count or 0
    input_count = official_count + estimated_count
    source_proportions = {
        "official": official_count / input_count if input_count else (1.0 if manifest.source_type.value == "official" else 0.0),
        "estimated": estimated_count / input_count if input_count else (1.0 if manifest.source_type.value != "official" else 0.0),
    }
    magic = (
        {
            "wins_needed_for_tie_or_tiebreak": magic_number.wins_needed,
            "strict_wins_needed": magic_number.strict_wins_needed,
            "limiting_competitor": magic_number.competitor,
            "combined_magic_number": magic_number.combined_magic_number,
            "combined_tie_number": magic_number.combined_tie_number,
            "combined_definition": magic_number.combined_definition,
            "kt_current_wins": magic_number.kt_current_wins,
            "competitor_current_losses": magic_number.competitor_current_losses,
            "ss_current_losses": magic_number.ss_current_losses,
            "season_games": magic_number.season_games,
        }
        if magic_number is not None
        else None
    )
    date_rows = date_confirmation_probabilities(result)
    date_confirmation = [
        {"date": row.date.isoformat(), "probability": row.probability, "count": row.count} for row in date_rows
    ]
    rank_probabilities = {
        team: {str(rank): result.rank_probability(team, rank) for rank in (1, 2, 3)}
        for team in sorted(result.rank_counts)
    }
    top_three_probabilities = {
        team: result.top_three_probability(team) for team in sorted(result.rank_counts)
    }
    most_likely_confirmation = max(date_rows, key=lambda row: row.probability) if date_rows else None
    estimated_makeup_dates = [
        forecast.estimated_game_date
        for forecast in remaining_forecasts
        if forecast.estimated_game_date is not None
    ]
    return {
        "engine": "KT Championship Engine",
        "version": "0.1.0",
        "simulations": result.simulations,
        "seed": result.seed,
        "kt_first_place_probability": result.kt_first_place_probability,
        "ss_first_place_probability": result.ss_first_place_probability,
        "kt_expected_final_wins": win_stats["KT"]["mean"],
        "ss_expected_final_wins": win_stats["SS"]["mean"],
        "lg_expected_final_wins": win_stats["LG"]["mean"],
        "final_win_stats": win_stats,
        "rank_probabilities": rank_probabilities,
        "top_three_probabilities": top_three_probabilities,
        "rank_probability_note": (
            "동률이 공식 타이브레이크로 해소되지 않은 경우 해당 순위 구간에 fractional credit을 부여하며, "
            "KT-삼성 단독 1위 동률에는 설정된 단일경기 타이브레이크 확률을 적용합니다."
        ),
        "first_place_counts": result.first_place_counts,
        "co_champion_before_tiebreak_count": result.co_champion_count,
        "tiebreak_resolved_count": result.tiebreak_resolved_count,
        "unknown_confirmation_count": sum(value is None for value in result.first_confirmation_dates),
        "kt_won_unknown_confirmation_count": result.kt_won_unknown_confirmation_count,
        "kt_won_unknown_confirmation_probability": result.kt_won_unknown_confirmation_count / result.simulations,
        "unresolved_first_place_count": result.unresolved_first_place_count,
        "linked_game_sample_count": result.linked_game_sample_count,
        "magic_number": magic,
        "date_confirmation_probabilities": date_confirmation,
        "most_likely_confirmation_date": most_likely_confirmation.date.isoformat()
        if most_likely_confirmation
        else None,
        "most_likely_confirmation_probability": most_likely_confirmation.probability if most_likely_confirmation else None,
        "estimated_makeup_date_count": len(estimated_makeup_dates),
        "estimated_makeup_date_start": min(estimated_makeup_dates).isoformat() if estimated_makeup_dates else None,
        "estimated_makeup_date_end": max(estimated_makeup_dates).isoformat() if estimated_makeup_dates else None,
        "estimated_schedule_method": manifest.estimated_schedule_method,
        "risk_games_top5": risk_games,
        "risk_scope": "KT/SS remaining games",
        "data_as_of": manifest.as_of.isoformat(),
        "data_as_of_precision": manifest.as_of_precision,
        "data_retrieved_at": manifest.retrieved_at.isoformat(),
        "data_source_type": manifest.source_type.value,
        "data_stale": manifest.stale,
        "warnings": manifest.warnings,
        "configured_base_weight": configured_base_weight,
        "configured_jev_weight": configured_jev_weight,
        "effective_base_weight": effective_base_weight,
        "effective_jev_weight": effective_jev_weight,
        "jev_status_counts": jev_status_counts,
        "forecast_mode": forecast_mode,
        "jev_preflight_status": preflight.jev_status.value if preflight else "not_applicable",
        "jev_preflight_http_status": preflight.jev_http_status if preflight else None,
        "jev_preflight_display": jev_preflight_display,
        "jev_successful_game_count": jev_successful_game_count,
        "jev_failed_call_count": jev_failed_call_count,
        "base_only_game_count": base_only_game_count,
        "remaining_game_count": len(remaining_forecasts),
        "actual_result_count": sum(forecast.actual_result is not None for forecast in forecasts),
        "feature_quality_counts": feature_quality_counts,
        "source_record_counts": {"official": official_count, "estimated": estimated_count},
        "source_proportions": source_proportions,
        "inferred_schedule_identity_count": manifest.inferred_schedule_record_count or 0,
        "tiebreak_policy": config.tiebreak_policy if config else "single_game",
        "future_game_tie_model": "bernoulli_no_ties",
    }


def _markdown_summary(summary: dict[str, object]) -> str:
    final_stats = summary["final_win_stats"]
    magic = summary["magic_number"]
    if isinstance(magic, dict):
        magic_line = f"- KT-삼성 결합 매직넘버: {magic['combined_magic_number']}"
        magic_alias = f"- 현재 매직넘버(결합): {magic['combined_magic_number']}"
        magic_detail = (
            "- 계산: 승/(승+패)를 정확한 분수로 비교; 현재 무승부와 잔여 맞대결 연동 반영. "
            "KT 맞대결 승리는 KT 승+삼성 패로 2개로 집계; 향후 무승부도 최악 조건 검증. "
            "결합 수치는 삼성 상대 기준이며, 전체 경쟁팀 자력 확정과 별개."
        )
        kt_only_magic_detail = (
            f"- KT 단독 매직넘버(추가 승리): {magic['strict_wins_needed']}승"
        )
        tie_detail = f"- 삼성 이상 승률 보장 기준(결합) · 동률은 우승 미확정: {magic['combined_tie_number']}"
        kt_additional_detail = f"- KT 단독 추가승수(동률 또는 타이브레이크 도달): {magic['wins_needed_for_tie_or_tiebreak']}승"
    else:
        magic_line = "- 현재 매직넘버: unknown"
        magic_alias = ""
        magic_detail = ""
        kt_only_magic_detail = ""
        tie_detail = ""
        kt_additional_detail = ""
    lines = [
        "# KT Championship Engine",
        "",
    ]
    warnings = summary["warnings"]
    if warnings:
        lines.extend(["⚠️ 데이터 경고: " + " / ".join(warnings), ""])
    lines.extend(
        [
            f"- KT 1위 확률: {summary['kt_first_place_probability']:.4%}",
            f"- 삼성 1위 확률: {summary['ss_first_place_probability']:.4%}",
            f"- KT 예상 최종승수: {summary['kt_expected_final_wins']:.2f}",
            f"- 삼성 예상 최종승수: {summary['ss_expected_final_wins']:.2f}",
            f"- LG 예상 최종승수: {summary['lg_expected_final_wins']:.2f}",
            f"- 시뮬레이션: {summary['simulations']:,}회 (seed={summary['seed']})",
            f"- 연결 맞대결 샘플 수: {summary['linked_game_sample_count']}",
            f"- 결과 모드: {summary['forecast_mode']}",
            f"- Jev 사전 연결 점검: {summary['jev_preflight_display']}",
            f"- Jev 성공 경기 수: {summary['jev_successful_game_count']}",
            f"- Jev 실패 호출 수: {summary['jev_failed_call_count']}",
            f"- Base-only 경기 수: {summary['base_only_game_count']}",
            magic_line,
            magic_alias,
            magic_detail,
            tie_detail,
            kt_only_magic_detail,
            kt_additional_detail,
            "",
            "## 최종 1~3위 확률",
            "",
            "| 구단 | 1위 | 2위 | 3위 | Top 3 포함 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    rank_rows = sorted(
        summary["top_three_probabilities"],
        key=lambda team: (
            -summary["top_three_probabilities"][team],
            -summary["rank_probabilities"][team]["1"],
            team,
        ),
    )
    for team in rank_rows:
        probabilities = summary["rank_probabilities"][team]
        label = TEAM_LABELS.get(team, team)
        lines.append(
            f"| {label} | {probabilities['1']:.2%} | {probabilities['2']:.2%} | "
            f"{probabilities['3']:.2%} | {summary['top_three_probabilities'][team]:.2%} |"
        )
    lines.extend(
        [
            "",
            f"- 순위 동률 처리: {summary['rank_probability_note']}",
            "",
            "## 최종 승수 분위수",
            "",
        ]
    )
    for team in ("KT", "SS", "LG"):
        if team in final_stats:
            label = TEAM_LABELS.get(team, team)
            lines.append(
                f"- {label}: P05 {final_stats[team]['p05']:.0f}, P50 {final_stats[team]['p50']:.0f}, "
                f"P95 {final_stats[team]['p95']:.0f}"
            )
    lines.extend(
        [
            "",
            "## 위험 경기 TOP 5",
            "",
            f"(범위: {summary['risk_scope']})",
            "",
        ]
    )
    for game in summary["risk_games_top5"]:
        lines.append(f"- {game['game_id']}: {game['team']} vs {game['opponent']} ({game['combined_probability']:.3f})")
    date_rows = summary["date_confirmation_probabilities"]
    lines.extend(["", "## 날짜별 KT 1위 확정 확률", ""])
    if date_rows:
        lines.extend(["| 날짜 | 확률 | 시뮬레이션 수 |", "|---|---:|---:|"])
        lines.extend(f"| {row['date']} | {row['probability']:.2%} | {row['count']:,} |" for row in date_rows)
        lines.extend(
            [
                "",
                f"- 확정일을 알 수 없는 KT 우승 시뮬레이션: {summary['kt_won_unknown_confirmation_probability']:.2%}",
            ]
        )
        if summary["estimated_makeup_date_count"]:
            lines.append(
                f"- 날짜 미정 순연 경기 추정: {summary['estimated_makeup_date_count']}경기, "
                f"{summary['estimated_makeup_date_start']}~{summary['estimated_makeup_date_end']}"
            )
            lines.append(f"- 날짜 추정 방식: {summary['estimated_schedule_method']}")
    else:
        lines.append("- 날짜가 확정된 잔여경기가 없습니다.")
    lines.extend(
        [
            "",
            "## 데이터 갱신 시각",
            "",
            f"- 기준 시각(as_of): {summary['data_as_of']}",
            f"- 기준 정밀도(as_of_precision): {summary['data_as_of_precision']}",
            f"- 수집 시각(retrieved_at): {summary['data_retrieved_at']}",
            f"- source_type: {summary['data_source_type']}",
            f"- stale: {summary['data_stale']}",
            f"- 입력 비율(official/estimated): {summary['source_proportions']['official']:.2%} / "
            f"{summary['source_proportions']['estimated']:.2%}",
            f"- 일정 식별 추정 행: {summary['inferred_schedule_identity_count']}",
            f"- 미래 경기 무승부 모델: {summary['future_game_tie_model']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_forecasts(path: Path, forecasts: list[GameForecast]) -> None:
    fieldnames = list(GameForecast.model_fields)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for forecast in forecasts:
            row = forecast.model_dump(mode="json")
            row["jev_components"] = json.dumps(row["jev_components"], ensure_ascii=False, sort_keys=True)
            writer.writerow(row)


def _write_date_confirmation(path: Path, result: SimulationResult) -> None:
    rows = date_confirmation_probabilities(result)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["date", "probability", "count"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({"date": row.date.isoformat(), "probability": row.probability, "count": row.count})


def _write_win_distribution(path: Path, result: SimulationResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["team", "wins", "count", "probability"], lineterminator="\n")
        writer.writeheader()
        for team in sorted(result.team_win_totals):
            values, counts = np.unique(result.team_win_totals[team], return_counts=True)
            for wins, count in zip(values, counts, strict=True):
                writer.writerow(
                    {
                        "team": team,
                        "wins": int(wins),
                        "count": int(count),
                        "probability": float(count / result.simulations),
                    }
                )


def _write_rank_distribution(path: Path, result: SimulationResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["team", "rank", "equivalent_count", "probability"],
            lineterminator="\n",
        )
        writer.writeheader()
        for team in sorted(result.rank_counts):
            for rank in sorted(result.rank_counts[team]):
                count = result.rank_counts[team][rank]
                writer.writerow(
                    {
                        "team": team,
                        "rank": rank,
                        "equivalent_count": count,
                        "probability": count / result.simulations,
                    }
                )
