from __future__ import annotations

import hashlib
from datetime import date, datetime

import httpx2
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from ..schemas import EvidenceStatus, Game, GameStatus, LineupEvidence, StartingPitcherEvidence

GAME_LIST_API_URL = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
LINEUP_API_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetLineUpAnalysis"
TEAM_CODES = {
    "KT": "KT",
    "SS": "SS",
    "LG": "LG",
    "OB": "DO",
    "NC": "NC",
    "SK": "SSG",
    "HT": "KI",
    "LT": "LOT",
    "HH": "HAN",
    "WO": "KIW",
}


class GameCenterGame(BaseModel):
    model_config = ConfigDict(extra="allow")

    G_ID: str
    AWAY_ID: str
    HOME_ID: str
    T_PIT_P_NM: str | None = None
    B_PIT_P_NM: str | None = None
    START_PIT_CK: int | None = None


class GameCenterResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    game: list[GameCenterGame]


class LineupFlag(BaseModel):
    LINEUP_CK: bool | int


class TeamLineupHeader(BaseModel):
    T_ID: str
    G_ID: str


class GridCell(BaseModel):
    Text: str | None = None


class GridRow(BaseModel):
    row: list[GridCell]


class LineupGrid(BaseModel):
    rows: list[GridRow] = Field(default_factory=list)


class LineupEnvelope(
    RootModel[
        tuple[
            list[LineupFlag],
            list[TeamLineupHeader],
            list[TeamLineupHeader],
            list[str],
            list[str],
        ]
    ]
):
    pass


def collect_gamecenter_evidence(
    games: list[Game],
    client: httpx2.Client,
    *,
    season: int,
) -> tuple[list[Game], list[str], list[str]]:
    scheduled = [game for game in games if game.status is GameStatus.SCHEDULED and game.game_date is not None]
    by_date: dict[date, list[Game]] = {}
    for game in scheduled:
        by_date.setdefault(game.game_date, []).append(game)
    game_rows: dict[str, tuple[GameCenterGame, str, datetime]] = {}
    source_hashes: list[str] = []
    warnings: list[str] = []
    request_headers = {"Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx"}
    for game_date, _date_games in sorted(by_date.items()):
        retrieved_at = datetime.now().astimezone()
        try:
            response = client.post(
                GAME_LIST_API_URL,
                headers=request_headers,
                data={"leId": "1", "srId": "0,1,3,4,5,6,7,9", "date": game_date.strftime("%Y%m%d")},
            )
            response.raise_for_status()
            source_hash = hashlib.sha256(response.content).hexdigest()
            payload = GameCenterResponse.model_validate(response.json())
        except (httpx2.HTTPError, ValueError, ValidationError):
            warnings.append(f"could not collect official game-center starters for {game_date.isoformat()}")
            continue
        source_hashes.append(source_hash)
        for row in payload.game:
            game_rows[row.G_ID] = (row, source_hash, retrieved_at)
    enriched: list[Game] = []
    for game in games:
        info = game_rows.get(game.game_id)
        if game not in scheduled or info is None:
            enriched.append(game)
            continue
        row, game_hash, game_retrieved_at = info
        if TEAM_CODES.get(row.AWAY_ID) != game.away_team or TEAM_CODES.get(row.HOME_ID) != game.home_team:
            warnings.append(f"game-center team order did not match official schedule for {game.game_id}")
            enriched.append(game)
            continue
        try:
            lineup_response = client.post(
                LINEUP_API_URL,
                headers=request_headers,
                data={"leId": "1", "srId": "0", "seasonId": str(season), "gameId": game.game_id},
            )
            lineup_response.raise_for_status()
            lineup_hash = hashlib.sha256(lineup_response.content).hexdigest()
            lineup_envelope = LineupEnvelope.model_validate(lineup_response.json())
            lineup_rows = _parse_lineups(lineup_envelope, game, lineup_hash, datetime.now().astimezone())
            source_hashes.append(lineup_hash)
        except (httpx2.HTTPError, IndexError, KeyError, TypeError, ValueError, ValidationError):
            lineup_rows = {}
            warnings.append(f"could not collect official game-center lineups for {game.game_id}")
        enriched.append(
            game.model_copy(
                update={
                    "away_starter": _starting_pitcher(
                        row.T_PIT_P_NM,
                        row.START_PIT_CK,
                        game.game_id,
                        GAME_LIST_API_URL,
                        game_hash,
                        game_retrieved_at,
                    ),
                    "home_starter": _starting_pitcher(
                        row.B_PIT_P_NM,
                        row.START_PIT_CK,
                        game.game_id,
                        GAME_LIST_API_URL,
                        game_hash,
                        game_retrieved_at,
                    ),
                    "away_lineup": lineup_rows.get("away", LineupEvidence()),
                    "home_lineup": lineup_rows.get("home", LineupEvidence()),
                }
            )
        )
    return _add_schedule_fatigue(enriched), source_hashes, warnings


def _starting_pitcher(
    name: str | None,
    confirmed: int | None,
    game_id: str,
    source_uri: str,
    source_hash: str,
    retrieved_at: datetime,
) -> StartingPitcherEvidence:
    normalized_name = name.strip() if name else ""
    if not normalized_name:
        return StartingPitcherEvidence()
    status = EvidenceStatus.OFFICIAL if confirmed == 1 else EvidenceStatus.ESTIMATED
    return StartingPitcherEvidence(
        name=normalized_name,
        status=status,
        source_game_id=game_id,
        source_uri=source_uri,
        source_hash=source_hash,
        retrieved_at=retrieved_at,
    )


def _parse_lineups(raw: LineupEnvelope, game: Game, source_hash: str, retrieved_at: datetime) -> dict[str, LineupEvidence]:
    flag = raw.root[0][0]
    result: dict[str, LineupEvidence] = {}
    for header_index, grid_index in ((1, 3), (2, 4)):
        header = raw.root[header_index][0]
        team = TEAM_CODES.get(header.T_ID)
        if team not in {game.away_team, game.home_team}:
            continue
        grid = LineupGrid.model_validate_json(raw.root[grid_index][0])
        players = []
        for lineup_row in grid.rows:
            cells = [cell.Text.strip() if cell.Text else "" for cell in lineup_row.row]
            if len(cells) >= 3 and cells[0].isnumeric() and cells[2]:
                players.append(f"{cells[0]} {cells[2]} ({cells[1]})")
        if not players:
            result["away" if team == game.away_team else "home"] = LineupEvidence()
            continue
        status = EvidenceStatus.OFFICIAL if flag.LINEUP_CK and header.G_ID == game.game_id else EvidenceStatus.ESTIMATED
        result["away" if team == game.away_team else "home"] = LineupEvidence(
            players=players,
            status=status,
            source_game_id=header.G_ID,
            source_uri=LINEUP_API_URL,
            source_hash=source_hash,
            retrieved_at=retrieved_at,
        )
    return result


def _add_schedule_fatigue(games: list[Game]) -> list[Game]:
    dated = [game for game in games if game.simulation_date is not None]
    enriched: list[Game] = []
    for game in games:
        if not game.remaining or game.simulation_date is None:
            enriched.append(game)
            continue
        simulation_date = game.simulation_date
        fields: dict[str, int | None] = {}
        for side, team in (("away", game.away_team), ("home", game.home_team)):
            prior_dates = [
                candidate.simulation_date
                for candidate in dated
                if candidate.game_id != game.game_id
                and candidate.simulation_date is not None
                and candidate.simulation_date < simulation_date
                and team in {candidate.away_team, candidate.home_team}
            ]
            last_seven_start = simulation_date.toordinal() - 7
            games_last_seven = sum(
                candidate.game_id != game.game_id
                and candidate.simulation_date is not None
                and last_seven_start < candidate.simulation_date.toordinal() < simulation_date.toordinal()
                and team in {candidate.away_team, candidate.home_team}
                for candidate in dated
            )
            rest_days = (simulation_date - max(prior_dates)).days - 1 if prior_dates else None
            fields[f"{side}_rest_days"] = rest_days
            fields[f"{side}_games_last_7d"] = games_last_seven
        enriched.append(game.model_copy(update=fields))
    return enriched
