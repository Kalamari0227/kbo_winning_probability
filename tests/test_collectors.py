from datetime import UTC, date, datetime

from kt_championship_engine.collectors.kbo import KBOCollector
from kt_championship_engine.scheduling import estimate_makeup_dates
from kt_championship_engine.schemas import GameStatus, TeamStanding


def test_source_cutoff_and_retrieval_timestamp_are_temporally_bounded():
    source_html = "<div>2026년 09월19일 기준</div>"
    retrieved_at = datetime(2026, 9, 20, 14, tzinfo=UTC)
    assert KBOCollector._source_as_of_date(source_html) == date(2026, 9, 19)
    assert KBOCollector._bounded_as_of_datetime(date(2026, 9, 20), retrieved_at) == datetime(2026, 9, 20, tzinfo=UTC)


def test_schedule_api_rows_preserve_postponement_and_official_result():
    payload = {
        "rows": [
            {
                "row": [
                    {"Class": "day", "Text": "09.22(화)"},
                    {"Class": "time", "Text": "<b>18:30</b>"},
                    {
                        "Class": "play",
                        "Text": "<span>KT</span><em><span>vs</span></em><span>삼성</span>",
                    },
                    {
                        "Class": "relay",
                        "Text": "<a href='/Schedule/GameCenter/Main.aspx?gameDate=20260922&gameId=20260922KTSS0'>프리뷰</a>",
                    },
                    {"Class": None, "Text": "수원"},
                    {"Class": None, "Text": "-"},
                ]
            },
            {
                "row": [
                    {"Class": "time", "Text": "<b>18:30</b>"},
                    {
                        "Class": "play",
                            "Text": (
                                "<span>삼성</span><em><span class='lose'>2</span><span>vs</span>"
                                "<span class='win'>5</span></em><span>KT</span>"
                            ),
                    },
                    {
                        "Class": "relay",
                        "Text": "<a href='/Schedule/GameCenter/Main.aspx?gameDate=20260919&gameId=20260919SSKT0'>리뷰</a>",
                    },
                    {"Class": None, "Text": "-"},
                ]
            },
            {
                "row": [
                    {"Class": "day", "Text": "09.03(목)"},
                    {"Class": "time", "Text": "<b>18:30</b>"},
                    {
                        "Class": "play",
                        "Text": "<span>삼성</span><em><span>vs</span></em><span>KT</span>",
                    },
                    {"Class": None, "Text": "우천취소"},
                ]
            },
        ]
    }
    as_of = date(2026, 9, 20)
    retrieved_at = datetime(2026, 9, 20, 12, tzinfo=UTC)

    games = KBOCollector()._parse_schedule_payload(payload, as_of, retrieved_at, "a" * 64)

    assert len(games) == 3
    scheduled = next(game for game in games if game.status is GameStatus.SCHEDULED)
    assert scheduled.game_date == date(2026, 9, 22)
    assert scheduled.venue == "수원"
    final = next(game for game in games if game.status is GameStatus.FINAL)
    assert final.away_score == 2
    assert final.home_score == 5
    postponed = next(game for game in games if game.status is GameStatus.POSTPONED)
    assert postponed.game_date is None


def test_same_class_zero_score_placeholder_remains_an_official_scheduled_game():
    payload = {
        "rows": [
            {
                "row": [
                    {"Class": "day", "Text": "09.27(일)"},
                    {"Class": "time", "Text": "<b>17:00</b>"},
                    {
                        "Class": "play",
                        "Text": '<span>KT</span><em><span class="same">0</span><span>vs</span>'
                        '<span class="same">0</span></em><span>두산</span>',
                    },
                    {"Class": "relay", "Text": ""},
                    {"Class": None, "Text": "잠실"},
                ]
            }
        ]
    }

    games = KBOCollector()._parse_schedule_payload(
        payload,
        date(2026, 9, 27),
        datetime(2026, 9, 27, 8, tzinfo=UTC),
        "a" * 64,
    )

    assert len(games) == 1
    game = games[0]
    assert game.status is GameStatus.SCHEDULED
    assert game.game_date == date(2026, 9, 27)
    assert game.away_score is None
    assert game.home_score is None
    assert game.venue == "잠실"


def test_latest_results_reconcile_outdated_official_standings(game_factory):
    source_as_of = date(2026, 9, 26)
    retrieved_at = datetime(2026, 9, 27, 9, tzinfo=UTC)
    source_timestamp = datetime(2026, 9, 26, tzinfo=UTC)
    standings = [
        TeamStanding(
            season=2026,
            team_id="KT",
            team_name="KT",
            played=6,
            wins=4,
            losses=2,
            ties=0,
            win_pct=4 / 6,
            rank=1,
            as_of=source_timestamp,
            retrieved_at=retrieved_at,
            source_type="official",
            source_uri="https://example.test/standings",
            source_hash="a" * 64,
        ),
        TeamStanding(
            season=2026,
            team_id="DO",
            team_name="Doosan",
            played=2,
            wins=1,
            losses=1,
            ties=0,
            win_pct=0.5,
            rank=2,
            as_of=source_timestamp,
            retrieved_at=retrieved_at,
            source_type="official",
            source_uri="https://example.test/standings",
            source_hash="a" * 64,
        ),
    ]
    completed = game_factory(
        game_id="20260927KTOB0",
        game_date=date(2026, 9, 27),
        status="final",
        away_team="KT",
        home_team="DO",
        away_score=2,
        home_score=3,
        is_official_result=True,
        as_of=source_timestamp,
        retrieved_at=retrieved_at,
    )

    history = [
        game_factory(
            game_id=f"202609{20 + index}KTOB0",
            game_date=date(2026, 9, 20 + index),
            status="final",
            away_team="KT",
            home_team="DO" if index < 2 else "LG",
            away_score=4,
            home_score=2,
            is_official_result=True,
            as_of=source_timestamp,
            retrieved_at=retrieved_at,
        )
        for index in range(6)
    ]

    updated_standings, updated_games, effective_as_of, warnings = KBOCollector()._reconcile_latest_official_results(
        standings, [*history, completed], source_as_of, retrieved_at, "b" * 64
    )

    by_team = {standing.team_id: standing for standing in updated_standings}
    assert effective_as_of == date(2026, 9, 27)
    assert (by_team["KT"].played, by_team["KT"].wins, by_team["KT"].losses, by_team["KT"].rank) == (7, 4, 3, 2)
    assert (by_team["DO"].played, by_team["DO"].wins, by_team["DO"].losses, by_team["DO"].rank) == (3, 2, 1, 1)
    assert all(standing.as_of == datetime(2026, 9, 27, tzinfo=UTC) for standing in updated_standings)
    assert updated_games[0].as_of == datetime(2026, 9, 27, tzinfo=UTC)
    assert len(warnings) == 1


def test_over_cap_pending_rows_are_marked_with_inferred_identity(game_factory):
    rows = [
        game_factory(game_id=f"over-cap-{index}", game_date=date(2026, 9, 22))
        for index in range(17)
    ]
    selected, warnings = KBOCollector._deduplicate_schedule(rows, date(2026, 9, 20))
    assert len(selected) == 16
    assert all(game.schedule_identity == "inferred" for game in selected)
    assert any("identity inferred" in warning for warning in warnings)


def test_undated_postponements_get_estimated_dates_without_overwriting_official_dates(game_factory):
    official = game_factory(game_id="20261007-KT-DO", game_date=date(2026, 10, 7))
    postponed = [
        game_factory(game_id="20260520-postponed-KT-SS-1", status="postponed", game_date=None),
        game_factory(game_id="20260828-postponed-KT-SS-2", status="postponed", game_date=None),
        game_factory(
            game_id="20260828-postponed-LG-LOT-1", status="postponed", game_date=None, away_team="LG", home_team="LOT"
        ),
        game_factory(
            game_id="20260830-postponed-LG-LOT-2", status="postponed", game_date=None, away_team="LG", home_team="LOT"
        ),
    ]

    estimated = estimate_makeup_dates([official, *postponed])

    assert estimated[0].game_date == date(2026, 10, 7)
    assert all(game.game_date is None for game in estimated[1:])
    assert [game.estimated_game_date for game in estimated[1:3]] == [date(2026, 10, 8), date(2026, 10, 9)]
    assert [game.simulation_date for game in estimated[1:3]] == [date(2026, 10, 8), date(2026, 10, 9)]
    occupied: set[tuple[date, str]] = set()
    for game in estimated[1:]:
        assert game.estimated_game_date is not None
        for team in (game.away_team, game.home_team):
            slot = (game.estimated_game_date, team)
            assert slot not in occupied
            occupied.add(slot)


def test_gamecenter_marks_confirmed_pitchers_and_unconfirmed_lineups(game_factory):
    import json

    import httpx2

    from kt_championship_engine.collectors.gamecenter import collect_gamecenter_evidence
    from kt_championship_engine.schemas import EvidenceStatus

    game = game_factory(game_id="20260920KTSS0", away_team="KT", home_team="SS")
    grids = [
        json.dumps(
            {
                "rows": [
                    {
                        "row": [
                            {"Text": "1"},
                            {"Text": "중견수"},
                            {"Text": player},
                        ]
                    }
                ]
            }
        )
        for player in ("KT선수", "삼성선수")
    ]

    class FakeClient:
        def post(self, url, **kwargs):
            if url.endswith("GetKboGameList"):
                body = {
                    "game": [
                        {
                            "G_ID": game.game_id,
                            "AWAY_ID": "KT",
                            "HOME_ID": "SS",
                            "T_PIT_P_NM": "배제성 ",
                            "B_PIT_P_NM": "원태인",
                            "START_PIT_CK": 1,
                        }
                    ]
                }
            else:
                body = [
                    [{"LINEUP_CK": False}],
                    [{"T_ID": "KT", "G_ID": "20260919KTDO0"}],
                    [{"T_ID": "SS", "G_ID": "20260919SSNC0"}],
                    [grids[0]],
                    [grids[1]],
                ]
            return httpx2.Response(
                200,
                json=body,
                request=httpx2.Request("POST", url),
            )

    collected, source_hashes, warnings = collect_gamecenter_evidence([game], FakeClient(), season=2026)
    result = collected[0]
    assert result.away_starter.name == "배제성"
    assert result.away_starter.status is EvidenceStatus.OFFICIAL
    assert result.home_starter.status is EvidenceStatus.OFFICIAL
    assert result.away_lineup.status is EvidenceStatus.ESTIMATED
    assert result.home_lineup.players == ["1 삼성선수 (중견수)"]
    assert result.away_games_last_7d == 0
    assert len(source_hashes) == 2
    assert warnings == []
