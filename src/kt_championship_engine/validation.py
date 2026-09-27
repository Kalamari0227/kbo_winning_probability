from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .schemas import Snapshot, SourceType

EXPECTED_KBO_TEAM_IDS = frozenset({"KT", "SS", "LG", "KI", "DO", "NC", "SSG", "LOT", "HAN", "KIW"})


class SnapshotValidationError(ValueError):
    """Raised when a snapshot violates a simulation invariant."""


class StaleDataError(SnapshotValidationError):
    """Raised when a snapshot is older than the requested analysis cutoff."""


class ValidationReport(BaseModel):
    valid: bool
    remaining_counts: dict[str, int] = Field(default_factory=dict)
    official_count: int = 0
    estimated_count: int = 0
    inferred_schedule_count: int = 0
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    data_manifest: dict[str, Any] = Field(default_factory=dict)


def validate_snapshot(snapshot: Snapshot, *, as_of: datetime, allow_stale: bool) -> ValidationReport:
    warnings: list[str] = []
    errors: list[str] = []
    team_ids = [standing.team_id for standing in snapshot.standings]
    if len(team_ids) != 10 or len(set(team_ids)) != 10:
        errors.append("snapshot must contain exactly ten unique KBO teams")
    elif set(team_ids) != EXPECTED_KBO_TEAM_IDS:
        missing = sorted(EXPECTED_KBO_TEAM_IDS - set(team_ids))
        unexpected = sorted(set(team_ids) - EXPECTED_KBO_TEAM_IDS)
        errors.append(f"snapshot team set mismatch: missing={missing}, unexpected={unexpected}")
    if snapshot.season != snapshot.manifest.season:
        errors.append("snapshot and manifest season must match")

    for standing in snapshot.standings:
        if standing.season != snapshot.season:
            errors.append(f"standing {standing.team_id} has season={standing.season}, expected {snapshot.season}")
    for game in snapshot.games:
        if game.season != snapshot.season:
            errors.append(f"game {game.game_id} has season={game.season}, expected {snapshot.season}")

    date_precision = snapshot.manifest.as_of_precision == "date"
    manifest_is_newer = (
        snapshot.manifest.as_of.date() > as_of.date()
        if date_precision
        else snapshot.manifest.as_of > as_of
    )
    if manifest_is_newer:
        errors.append(
            f"snapshot as_of={snapshot.manifest.as_of.isoformat()} is newer than "
            f"requested cutoff {as_of.isoformat()}"
        )

    records = [*snapshot.standings, *snapshot.games]
    record_is_newer = (
        (lambda record: record.as_of.date() > as_of.date())
        if date_precision
        else (lambda record: record.as_of > as_of)
    )
    record_is_older = (
        (lambda record: record.as_of.date() < as_of.date())
        if date_precision
        else (lambda record: record.as_of < as_of)
    )
    future_record_count = sum(record_is_newer(record) for record in records)
    if future_record_count:
        errors.append(f"{future_record_count} records are newer than requested cutoff {as_of.isoformat()}")
    record_cutoff_stale = any(record_is_older(record) for record in records)
    manifest_is_older = (
        snapshot.manifest.as_of.date() < as_of.date()
        if date_precision
        else snapshot.manifest.as_of < as_of
    )
    cutoff_stale = manifest_is_older or record_cutoff_stale
    stale = snapshot.manifest.stale or cutoff_stale
    if cutoff_stale:
        warnings.append(f"snapshot as_of={snapshot.manifest.as_of.isoformat()} is older than requested {as_of.isoformat()}")
        if not allow_stale:
            raise StaleDataError(warnings[-1])
    elif snapshot.manifest.stale:
        warnings.append("snapshot manifest is explicitly marked stale")
        if not allow_stale:
            raise StaleDataError(warnings[-1])

    if len({game.game_id for game in snapshot.games}) != len(snapshot.games):
        errors.append("game_id values must be unique after canonicalization")

    remaining_counts = {team_id: 0 for team_id in team_ids}
    final_counts = {team_id: 0 for team_id in team_ids}
    result_counts = {team_id: {"wins": 0, "losses": 0, "ties": 0} for team_id in team_ids}
    for game in snapshot.games:
        for team_id in (game.away_team, game.home_team):
            if team_id not in remaining_counts:
                errors.append(f"game {game.game_id} references unknown team {team_id}")
                continue
            if game.remaining:
                remaining_counts[team_id] += 1
            else:
                final_counts[team_id] += 1
        if not game.remaining and game.away_team in result_counts and game.home_team in result_counts:
            if game.away_score == game.home_score:
                result_counts[game.away_team]["ties"] += 1
                result_counts[game.home_team]["ties"] += 1
            elif game.away_score > game.home_score:
                result_counts[game.away_team]["wins"] += 1
                result_counts[game.home_team]["losses"] += 1
            else:
                result_counts[game.home_team]["wins"] += 1
                result_counts[game.away_team]["losses"] += 1

    observed_inferred_schedule_count = sum(game.schedule_identity == "inferred" for game in snapshot.games)
    if (
        snapshot.manifest.inferred_schedule_record_count is not None
        and snapshot.manifest.inferred_schedule_record_count != observed_inferred_schedule_count
    ):
        errors.append(
            "manifest inferred schedule count disagrees with game records: "
            f"manifest={snapshot.manifest.inferred_schedule_record_count}, observed={observed_inferred_schedule_count}"
        )

    for standing in snapshot.standings:
        total = standing.played + remaining_counts.get(standing.team_id, 0)
        if total != 144:
            errors.append(
                f"{standing.team_id} has played={standing.played} and remaining="
                f"{remaining_counts.get(standing.team_id, 0)}; expected 144"
            )
        if final_counts.get(standing.team_id, 0) > standing.played:
            errors.append(f"{standing.team_id} has more final game rows than played games")
        if final_counts.get(standing.team_id, 0) == standing.played:
            observed = result_counts[standing.team_id]
            expected = {"wins": standing.wins, "losses": standing.losses, "ties": standing.ties}
            if observed != expected:
                errors.append(
                    f"{standing.team_id} standings disagree with completed results: observed={observed}, expected={expected}"
                )

    official_count = sum(1 for record in [*snapshot.standings, *snapshot.games] if record.source_type is SourceType.OFFICIAL)
    official_count += sum(game.official_evidence_count for game in snapshot.games)
    estimated_count = sum(
        1
        for record in [*snapshot.standings, *snapshot.games]
        if record.source_type in {SourceType.ESTIMATED, SourceType.MANUAL, SourceType.STALE}
    )
    estimated_count += sum(game.estimated_evidence_count for game in snapshot.games)
    estimated_count += sum(game.estimated_game_date is not None for game in snapshot.games)
    if errors:
        raise SnapshotValidationError("; ".join(errors))
    return ValidationReport(
        valid=True,
        remaining_counts=remaining_counts,
        official_count=official_count,
        estimated_count=estimated_count,
        inferred_schedule_count=observed_inferred_schedule_count,
        stale=stale,
        warnings=warnings,
        data_manifest=snapshot.manifest.model_dump(mode="json"),
    )
