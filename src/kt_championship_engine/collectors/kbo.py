from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, date, datetime, time
from io import StringIO
from pathlib import Path
from typing import Any

import httpx2
import pandas as pd

from ..data_io import load_snapshot
from ..network import create_client
from ..scheduling import ESTIMATED_MAKEUP_DATE_METHOD, estimate_makeup_dates
from ..schemas import DataManifest, Game, GameStatus, Snapshot, SourceType, TeamStanding
from .gamecenter import GAME_LIST_API_URL, LINEUP_API_URL, collect_gamecenter_evidence


class CollectorError(RuntimeError):
    """Raised when an official source cannot be parsed safely."""


TEAM_ALIASES = {
    "KT": "KT",
    "KT 위즈": "KT",
    "KT Wiz": "KT",
    "삼성": "SS",
    "삼성 라이온즈": "SS",
    "Samsung Lions": "SS",
    "LG": "LG",
    "두산": "DO",
    "NC": "NC",
    "SSG": "SSG",
    "KIA": "KI",
    "롯데": "LOT",
    "한화": "HAN",
    "키움": "KIW",
}
SCHEDULE_VENUE_LABELS = frozenset(
    {"잠실", "수원", "문학", "대구", "광주", "사직", "창원", "대전", "고척", "포항", "울산", "청주", "군산"}
)


class KBOCollector:
    """Collect and normalize KBO pages without fabricating missing fields."""

    SCHEDULE_API_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList"

    def __init__(
        self,
        standings_url: str = "https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx",
        schedule_url: str = "https://www.koreabaseball.com/Schedule/Schedule.aspx",
        schedule_api_url: str = SCHEDULE_API_URL,
        timeout: float = 20.0,
        client: httpx2.Client | None = None,
    ) -> None:
        self.standings_url = standings_url
        self.schedule_url = schedule_url
        self.schedule_api_url = schedule_api_url
        self.timeout = timeout
        self._client = client

    @classmethod
    def from_local(cls, path: Path) -> Snapshot:
        return load_snapshot(path)

    def fetch(self, as_of: date | None = None) -> Snapshot:
        own_client = self._client is None
        season = as_of.year if as_of else date.today().year
        client = self._client or create_client(
            timeout_seconds=self.timeout,
            headers={
                "User-Agent": "KT-Championship-Engine/0.1 (+data provenance)",
                "Referer": self.schedule_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            standings_response = client.get(self.standings_url)
            schedule_page_response = client.get(self.schedule_url)
            schedule_response = client.post(
                self.schedule_api_url,
                data={"leId": "1", "srIdList": "0,9,6", "seasonId": str(season), "gameMonth": "", "teamId": ""},
            )
            standings_response.raise_for_status()
            schedule_page_response.raise_for_status()
            schedule_response.raise_for_status()
            retrieved_at = datetime.now(UTC)
            source_as_of = self._source_as_of_date(standings_response.text)
            if source_as_of is None:
                raise CollectorError("could not determine the official standings cutoff date")
            if as_of is not None and source_as_of > as_of:
                raise CollectorError(
                    f"official source is newer than requested cutoff: source={source_as_of.isoformat()} "
                    f"requested={as_of.isoformat()}"
                )
            effective_as_of = as_of or source_as_of
            standings_hash = hashlib.sha256(standings_response.content).hexdigest()
            schedule_hash = hashlib.sha256(schedule_response.content).hexdigest()
            standings = self._parse_standings(standings_response.text, source_as_of, retrieved_at, standings_hash)
            try:
                schedule_payload = schedule_response.json()
            except ValueError as exc:
                raise CollectorError("official KBO schedule endpoint returned non-JSON content") from exc
            games, schedule_warnings = self._parse_schedule_payload(
                schedule_payload,
                effective_as_of,
                retrieved_at,
                schedule_hash,
                return_warnings=True,
                allow_results_after_cutoff=as_of is None,
            )
            if not standings or not games:
                raise CollectorError("official KBO pages contained no parseable standings or games")
            reconciliation_warnings: list[str] = []
            if as_of is None:
                standings, games, effective_as_of, reconciliation_warnings = self._reconcile_latest_official_results(
                    standings, games, source_as_of, retrieved_at, schedule_hash
                )
            games = estimate_makeup_dates(games)
            estimated_makeup_count = sum(game.estimated_game_date is not None for game in games)
            makeup_warnings = (
                [f"estimated {estimated_makeup_count} undated postponed games for simulation"]
                if estimated_makeup_count
                else []
            )
            games, gamecenter_hashes, gamecenter_warnings = collect_gamecenter_evidence(
                games,
                client,
                season=season,
            )
            retrieved_at = datetime.now(UTC)
            official_evidence_records = sum(game.official_evidence_count for game in games)
            estimated_evidence_records = sum(game.estimated_evidence_count for game in games)
            manifest = DataManifest(
                season=season,
                as_of=self._bounded_as_of_datetime(effective_as_of, retrieved_at),
                as_of_precision="date",
                retrieved_at=retrieved_at,
                source_type=SourceType.OFFICIAL,
                source_uris=[
                    self.standings_url,
                    self.schedule_url,
                    self.schedule_api_url,
                    GAME_LIST_API_URL,
                    LINEUP_API_URL,
                ],
                source_hashes=[
                    standings_hash,
                    hashlib.sha256(schedule_page_response.content).hexdigest(),
                    schedule_hash,
                    *gamecenter_hashes,
                ],
                stale=as_of is not None and source_as_of < as_of,
                warnings=(
                    [
                        f"official source cutoff {source_as_of.isoformat()} is older than requested {as_of.isoformat()}"
                    ]
                    if as_of is not None and source_as_of < as_of
                    else []
                )
                + ["official source cutoff is date-granular; no intraday freshness is inferred"]
                + reconciliation_warnings
                + schedule_warnings
                + makeup_warnings
                + gamecenter_warnings,
                official_record_count=len(standings) + len(games) + official_evidence_records,
                estimated_record_count=estimated_evidence_records + estimated_makeup_count,
                inferred_schedule_record_count=sum(game.schedule_identity == "inferred" for game in games),
                estimated_schedule_method=ESTIMATED_MAKEUP_DATE_METHOD if estimated_makeup_count else None,
            )
            return Snapshot(season=season, standings=standings, games=games, manifest=manifest)
        except (httpx2.HTTPError, KeyError, TypeError) as exc:
            raise CollectorError(f"failed to fetch official KBO data: {exc}") from exc
        finally:
            if own_client:
                client.close()

    def _parse_standings(self, html: str, as_of: date, retrieved_at: datetime, source_hash: str) -> list[TeamStanding]:
        tables = pd.read_html(StringIO(html))
        table = next(
            (
                candidate
                for candidate in tables
                if any(str(column).strip() in {"팀명", "Team", "팀"} for column in candidate.columns)
                and any(str(column).strip() in {"승", "W", "Win"} for column in candidate.columns)
            ),
            None,
        )
        if table is None:
            raise CollectorError("could not locate standings table")
        rows: list[TeamStanding] = []
        for index, row in table.iterrows():
            team_name = str(self._cell(row, "팀명", "Team", "팀"))
            team_id = TEAM_ALIASES.get(team_name, team_name)
            wins = self._integer(self._cell(row, "승", "W", "Win"))
            losses = self._integer(self._cell(row, "패", "L", "Loss"))
            ties = self._integer(self._cell(row, "무", "D", "Tie"), default=0)
            played = self._integer(self._cell(row, "경기", "G", "Games"), default=wins + losses + ties)
            win_pct = self._float(self._cell(row, "승률", "WPCT", "Win%"), default=0.0)
            rows.append(
                TeamStanding(
                    season=as_of.year,
                    team_id=team_id,
                    team_name=team_name,
                    played=played,
                    wins=wins,
                    losses=losses,
                    ties=ties,
                    win_pct=win_pct,
                    rank=self._integer(self._cell(row, "순위", "Rank"), default=index + 1),
                    as_of=self._bounded_as_of_datetime(as_of, retrieved_at),
                    retrieved_at=retrieved_at,
                    source_type=SourceType.OFFICIAL,
                    source_uri=self.standings_url,
                    source_hash=source_hash,
                )
            )
        return rows

    def _parse_schedule_payload(
        self,
        payload: dict[str, Any],
        as_of: date,
        retrieved_at: datetime,
        source_hash: str,
        *,
        return_warnings: bool = False,
        allow_results_after_cutoff: bool = False,
    ) -> list[Game] | tuple[list[Game], list[str]]:
        rows: list[Game] = []
        current_date: date | None = None
        for index, raw_row in enumerate(payload.get("rows", [])):
            cells = raw_row.get("row", [])
            if not isinstance(cells, list):
                continue
            day_text = next((str(cell.get("Text", "")) for cell in cells if cell.get("Class") == "day"), "")
            if day_text:
                current_date = self._schedule_day(day_text, as_of.year)
            play = next((str(cell.get("Text", "")) for cell in cells if cell.get("Class") == "play"), "")
            match = re.search(r"<span>([^<]+)</span><em>(.*?)</em><span>([^<]+)</span>", play)
            if match is None:
                continue
            away = TEAM_ALIASES.get(match.group(1).strip(), "")
            home = TEAM_ALIASES.get(match.group(3).strip(), "")
            if not away or not home:
                continue
            venue = self._schedule_venue(cells)
            score_spans = re.findall(r'<span([^>]*)>(\d+)</span>', match.group(2))
            score_values = [int(value) for _, value in score_spans]
            has_placeholder_score = (
                len(score_spans) >= 2
                and score_values[:2] == [0, 0]
                and all(re.search(r'\bclass=["\']same["\']', attributes) for attributes, _ in score_spans[:2])
            )
            all_text = " ".join(str(cell.get("Text", "")) for cell in cells)
            game_id_match = re.search(r"gameId=([^&'\"\s]+)", all_text)
            game_id = game_id_match.group(1) if game_id_match else ""
            game_id_date = self._game_id_date(game_id, as_of.year)
            row_date = game_id_date or current_date
            if len(score_values) >= 2 and not has_placeholder_score:
                if row_date is not None and row_date > as_of and not allow_results_after_cutoff:
                    raise CollectorError(
                        f"schedule contains a final game after the official cutoff: {row_date.isoformat()}"
                    )
                status = GameStatus.FINAL
                away_score, home_score = score_values[:2]
                is_official_result = True
                game_date = row_date
            else:
                status = GameStatus.SCHEDULED if current_date and current_date >= as_of else GameStatus.POSTPONED
                away_score = home_score = None
                is_official_result = False
                game_date = row_date if status is GameStatus.SCHEDULED else None
            if not game_id:
                kind = "scheduled" if status is GameStatus.SCHEDULED else "postponed"
                date_key = current_date.strftime("%Y%m%d") if current_date else as_of.strftime("%Y%m%d")
                game_id = f"{date_key}-{kind}-{away}-{home}-{index:03d}"
            rows.append(
                Game(
                    game_id=game_id,
                    season=as_of.year,
                    game_date=game_date,
                    status=status,
                    away_team=away,
                    home_team=home,
                    venue=venue,
                    away_score=away_score,
                    home_score=home_score,
                    is_official_result=is_official_result,
                    as_of=self._bounded_as_of_datetime(as_of, retrieved_at),
                    retrieved_at=retrieved_at,
                    source_type=SourceType.OFFICIAL,
                    source_uri=self.schedule_api_url,
                    source_hash=source_hash,
                )
            )
        games, warnings = self._deduplicate_schedule(rows, as_of)
        return (games, warnings) if return_warnings else games

    @staticmethod
    def _schedule_venue(cells: list[dict[str, Any]]) -> str | None:
        for cell in cells:
            venue = str(cell.get("Text", "")).strip()
            if venue in SCHEDULE_VENUE_LABELS:
                return venue
        return None

    def _reconcile_latest_official_results(
        self,
        standings: list[TeamStanding],
        games: list[Game],
        source_as_of: date,
        retrieved_at: datetime,
        schedule_hash: str,
    ) -> tuple[list[TeamStanding], list[Game], date, list[str]]:
        """Merge official completed games missing from a date-lagged standings page."""

        standings_by_team = {standing.team_id: standing for standing in standings}
        final_counts: Counter[str] = Counter(
            team
            for game in games
            if game.status is GameStatus.FINAL
            for team in (game.away_team, game.home_team)
        )
        missing_counts = {
            team: final_counts[team] - standing.played
            for team, standing in standings_by_team.items()
        }
        ahead = [team for team, count in missing_counts.items() if count < 0]
        if ahead:
            raise CollectorError(
                "official standings are newer than completed schedule results for " + ", ".join(sorted(ahead))
            )
        if not any(missing_counts.values()):
            return standings, games, source_as_of, []

        pending = missing_counts.copy()
        candidates = sorted(
            (
                game
                for game in games
                if game.status is GameStatus.FINAL and game.game_date is not None and game.game_date >= source_as_of
            ),
            key=lambda game: (game.game_date, game.game_id),
            reverse=True,
        )
        additional_results: list[Game] = []
        for game in candidates:
            if pending.get(game.away_team, 0) <= 0 or pending.get(game.home_team, 0) <= 0:
                continue
            additional_results.append(game)
            pending[game.away_team] -= 1
            pending[game.home_team] -= 1
        unresolved = [team for team, count in pending.items() if count]
        if unresolved:
            raise CollectorError(
                "could not match newer official standings totals to completed schedule results for "
                + ", ".join(sorted(unresolved))
            )

        result_deltas = {team: [0, 0, 0] for team in standings_by_team}
        for game in additional_results:
            if game.away_score == game.home_score:
                result_deltas[game.away_team][2] += 1
                result_deltas[game.home_team][2] += 1
            elif game.away_score > game.home_score:
                result_deltas[game.away_team][0] += 1
                result_deltas[game.home_team][1] += 1
            else:
                result_deltas[game.home_team][0] += 1
                result_deltas[game.away_team][1] += 1

        effective_as_of = max(game.game_date for game in additional_results if game.game_date is not None)
        effective_timestamp = self._bounded_as_of_datetime(effective_as_of, retrieved_at)
        combined_source_uri = f"{self.standings_url} | {self.schedule_api_url}"
        reconciled: list[TeamStanding] = []
        for standing in standings:
            wins = standing.wins + result_deltas[standing.team_id][0]
            losses = standing.losses + result_deltas[standing.team_id][1]
            ties = standing.ties + result_deltas[standing.team_id][2]
            reconciled.append(
                standing.model_copy(
                    update={
                        "played": standing.played + sum(result_deltas[standing.team_id]),
                        "wins": wins,
                        "losses": losses,
                        "ties": ties,
                        "win_pct": wins / (wins + losses) if wins + losses else 0.0,
                        "as_of": effective_timestamp,
                        "retrieved_at": retrieved_at,
                        "source_uri": combined_source_uri,
                        "source_hash": hashlib.sha256(
                            f"{standing.source_hash}:{schedule_hash}".encode("ascii")
                        ).hexdigest(),
                    }
                )
            )

        reconciled.sort(key=lambda standing: (-standing.win_pct, standing.rank, standing.team_id))
        reconciled = [standing.model_copy(update={"rank": index}) for index, standing in enumerate(reconciled, 1)]
        reconciled_games = [game.model_copy(update={"as_of": effective_timestamp}) for game in games]
        warnings = [
            f"merged {len(additional_results)} newer official schedule results through {effective_as_of.isoformat()} "
            f"because the standings page cutoff remained {source_as_of.isoformat()}"
        ]
        return reconciled, reconciled_games, effective_as_of, warnings

    @staticmethod
    def _deduplicate_schedule(rows: list[Game], as_of: date) -> tuple[list[Game], list[str]]:
        """Keep the sixteen regular-season games in each unordered matchup.

        KBO's schedule API keeps the original rainout row and also exposes its
        replacement row.  A matchup slot is therefore counted once, preferring
        a confirmed future date and otherwise retaining an undated postponement.
        """

        grouped: dict[tuple[str, str], list[Game]] = {}
        for game in rows:
            pair = tuple(sorted((game.away_team, game.home_team)))
            grouped.setdefault(pair, []).append(game)

        selected: list[Game] = []
        dropped = 0
        undated = 0
        for pair, pair_games in sorted(grouped.items()):
            finals = [game for game in pair_games if game.status is GameStatus.FINAL]
            if len(finals) > 16:
                raise CollectorError(f"official schedule has more than sixteen final games for {pair[0]} vs {pair[1]}")
            remaining_slots = 16 - len(finals)
            unresolved = [game for game in pair_games if game.status is not GameStatus.FINAL]
            future = sorted(
                (game for game in unresolved if game.game_date is not None and game.game_date >= as_of),
                key=lambda game: (game.game_date, game.game_id),
            )
            chosen = future[:remaining_slots]
            candidates = [game for game in unresolved if game not in chosen]
            candidates.sort(key=lambda game: (game.game_date or date.min, game.game_id))
            for game in candidates:
                if len(chosen) >= remaining_slots:
                    break
                chosen.append(game.model_copy(update={"game_date": None, "status": GameStatus.POSTPONED}))
                undated += 1
            dropped += len(pair_games) - len(finals) - len(chosen)
            selected.extend(finals)
            if len(pair_games) > 16:
                chosen = [
                    game.model_copy(update={"schedule_identity": "inferred"})
                    if game.status is not GameStatus.FINAL
                    else game
                    for game in chosen
                ]
            selected.extend(chosen)

        warnings: list[str] = []
        if dropped:
            warnings.append(
                f"deduplicated {dropped} original/rescheduled rows; identity inferred by the sixteen-game matchup cap"
            )
            warnings.append(
                "ambiguous schedule identity remains for over-cap pending rows; retained rows stay official source "
                "records with schedule_identity=inferred and this assumption is audited"
            )
        if undated:
            warnings.append(f"retained {undated} undated postponed games")
        return selected, warnings

    @staticmethod
    def _schedule_day(value: str, year: int) -> date | None:
        match = re.search(r"(\d{2})\.(\d{2})", value)
        if match is None:
            return None
        return date(year, int(match.group(1)), int(match.group(2)))

    @staticmethod
    def _game_id_date(game_id: str, year: int) -> date | None:
        match = re.match(r"(\d{8})", game_id)
        if match is None:
            return None
        try:
            parsed = date(
                int(match.group(1)[:4]),
                int(match.group(1)[4:6]),
                int(match.group(1)[6:]),
            )
        except ValueError:
            return None
        return parsed if parsed.year == year else None

    @staticmethod
    def _source_as_of_date(html: str) -> date | None:
        match = re.search(r"\(?\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*기준\)?", html)
        if match is None:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @staticmethod
    def _bounded_as_of_datetime(value: date, retrieved_at: datetime) -> datetime:
        """Represent a date-only source cutoff without implying retrieval-time freshness."""

        return datetime.combine(value, time.min, tzinfo=UTC)

    @staticmethod
    def _cell(row: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if name in row.index:
                return row[name]
        return default

    @staticmethod
    def _integer(value: Any, default: int | None = None) -> int:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            if default is None:
                raise CollectorError("required integer cell is missing")
            return default
        return int(float(str(value).replace(",", "").strip()))

    @staticmethod
    def _float(value: Any, default: float | None = None) -> float:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            if default is None:
                raise CollectorError("required numeric cell is missing")
            return default
        text = str(value).replace("%", "").strip()
        number = float(text)
        return number / 100 if number > 1 else number

    @staticmethod
    def _date(value: Any) -> date | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        parsed = pd.to_datetime(str(value), errors="coerce")
        return None if pd.isna(parsed) else parsed.date()
