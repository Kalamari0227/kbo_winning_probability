from datetime import UTC, datetime

import pytest

from kt_championship_engine.validation import StaleDataError, validate_snapshot

AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_undated_postponement_counts_as_remaining(mini_snapshot):
    report = validate_snapshot(mini_snapshot, as_of=AS_OF, allow_stale=True)
    assert report.remaining_counts["KT"] == 2
    assert report.remaining_counts["SS"] == 2


def test_stale_snapshot_requires_explicit_flag(stale_snapshot):
    with pytest.raises(StaleDataError):
        validate_snapshot(stale_snapshot, as_of=AS_OF, allow_stale=False)


def test_future_snapshot_is_rejected_for_earlier_cutoff(mini_snapshot):
    with pytest.raises(ValueError, match="newer than requested"):
        validate_snapshot(
            mini_snapshot,
            as_of=datetime(2026, 8, 1, 12, tzinfo=UTC),
            allow_stale=True,
        )


def test_precise_snapshot_respects_intraday_cutoff(mini_snapshot):
    with pytest.raises(ValueError, match="newer than requested"):
        validate_snapshot(
            mini_snapshot,
            as_of=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
            allow_stale=True,
        )
    report = validate_snapshot(
        mini_snapshot,
        as_of=datetime(2026, 9, 20, 13, 0, tzinfo=UTC),
        allow_stale=True,
    )
    assert report.stale is True


def test_stale_record_provenance_requires_explicit_flag(mini_snapshot):
    stale_record = mini_snapshot.standings[0].model_copy(
        update={"as_of": datetime(2026, 9, 19, 12, tzinfo=UTC)}
    )
    snapshot = mini_snapshot.model_copy(
        update={"standings": [stale_record, *mini_snapshot.standings[1:]]}
    )
    with pytest.raises(StaleDataError):
        validate_snapshot(snapshot, as_of=AS_OF, allow_stale=False)


def test_manifest_inferred_schedule_count_must_match_records(mini_snapshot):
    snapshot = mini_snapshot.model_copy(
        update={
            "manifest": mini_snapshot.manifest.model_copy(update={"inferred_schedule_record_count": 1}),
        }
    )
    with pytest.raises(ValueError, match="inferred schedule count"):
        validate_snapshot(snapshot, as_of=AS_OF, allow_stale=True)


def test_head_to_head_has_one_canonical_game_id(mini_snapshot):
    validate_snapshot(mini_snapshot, as_of=AS_OF, allow_stale=True)
    games = [game for game in mini_snapshot.games if {game.away_team, game.home_team} == {"KT", "SS"}]
    assert len({game.game_id for game in games}) == len(games)


def test_validation_report_records_source_counts(mini_snapshot):
    report = validate_snapshot(mini_snapshot, as_of=AS_OF, allow_stale=True)
    assert report.official_count == len(mini_snapshot.games) + len(mini_snapshot.standings)
    assert report.estimated_count == 0
