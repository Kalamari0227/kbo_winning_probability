from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any, TypedDict
from urllib.parse import urlsplit

from .schemas import EvidenceStatus, StartingPitcherEvidence

ASSET_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/assets/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
    **{
        f"/assets/teams/{team}.png": (f"teams/{team}.png", "image/png")
        for team in ("KT", "SS", "LG", "KI", "DO", "NC", "LOT", "SSG", "HAN", "KIW")
    },
}
TEAM_NAMES = {"KT": "KT Wiz", "SS": "삼성 라이온즈", "LG": "LG 트윈스"}


class StartingPitcherSummary(TypedDict):
    name: str | None
    status: EvidenceStatus


class RefreshError(RuntimeError):
    pass


def load_dashboard_state(project_root: Path) -> dict[str, Any]:
    output_dir = project_root / "artifacts" / "latest"
    summary_path = output_dir / "simulation_summary.json"
    snapshot_path = project_root / "data" / "snapshots" / "latest.json"
    with summary_path.open("r", encoding="utf-8") as stream:
        summary = json.load(stream)
    with snapshot_path.open("r", encoding="utf-8") as stream:
        snapshot = json.load(stream)

    remaining_by_team: Counter[str] = Counter()
    games_by_id = {game["game_id"]: game for game in snapshot["games"]}
    for game in snapshot["games"]:
        if game["status"] != "final":
            remaining_by_team[game["away_team"]] += 1
            remaining_by_team[game["home_team"]] += 1
    for row in snapshot["standings"]:
        if row["played"] + remaining_by_team[row["team_id"]] != 144:
            raise ValueError(f"{row['team_id']} game count does not equal 144")
    if _parse_timestamp(summary["data_retrieved_at"]) != _parse_timestamp(snapshot["manifest"]["retrieved_at"]):
        raise ValueError("snapshot and simulation artifacts are from different collection times")

    standings = [
        {
            "team": row["team_id"],
            "name": TEAM_NAMES.get(row["team_id"], row["team_name"]),
            "played": row["played"],
            "wins": row["wins"],
            "losses": row["losses"],
            "ties": row["ties"],
            "remaining": remaining_by_team[row["team_id"]],
            "source_type": row["source_type"],
        }
        for row in snapshot["standings"]
        if row["team_id"] in TEAM_NAMES
    ]

    forecasts_by_game: dict[str, list[dict[str, str]]] = defaultdict(list)
    forecast_path = output_dir / "game_forecasts.csv"
    with forecast_path.open("r", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("is_remaining", "").lower() == "true":
                forecasts_by_game[row["game_id"]].append(row)

    remaining_games: list[dict[str, Any]] = []
    for rows in forecasts_by_game.values():
        home_row = next((row for row in rows if row["is_home"].lower() == "true"), rows[0])
        away_row = next((row for row in rows if row["team"] != home_row["team"]), None)
        snapshot_game = games_by_id.get(home_row["game_id"])
        if snapshot_game is None:
            raise ValueError(f"forecast game is missing from snapshot: {home_row['game_id']}")
        official_date = home_row.get("game_date") or ""
        estimated_date = home_row.get("estimated_game_date") or ""
        remaining_games.append(
            {
                "game_id": home_row["game_id"],
                "date": official_date or estimated_date or None,
                "date_status": "official" if official_date else "estimated" if estimated_date else "unavailable",
                "venue": snapshot_game.get("venue"),
                "away_team": away_row["team"] if away_row else home_row["opponent"],
                "home_team": home_row["team"],
                "away_starter": _starter_summary(
                    StartingPitcherEvidence.model_validate(snapshot_game.get("away_starter") or {})
                ),
                "home_starter": _starter_summary(
                    StartingPitcherEvidence.model_validate(snapshot_game.get("home_starter") or {})
                ),
                "base_probability": _optional_float(home_row.get("base_probability")),
                "jev_probability": _optional_float(home_row.get("jev_probability")),
                "combined_probability": _optional_float(home_row.get("combined_probability")),
                "jev_status": home_row.get("jev_status", "unavailable"),
            }
        )
    remaining_games.sort(key=lambda row: (row["date"] or "9999-99-99", row["game_id"]))
    if len(remaining_games) != summary["remaining_game_count"]:
        raise ValueError("forecast rows do not match the official remaining game count")

    return {
        "summary": summary,
        "standings": standings,
        "remaining_games": remaining_games,
        "snapshot_manifest": snapshot["manifest"],
    }


def _starter_summary(evidence: StartingPitcherEvidence) -> StartingPitcherSummary:
    return {"name": evidence.name, "status": evidence.status}


def _optional_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def refresh_dashboard_data(project_root: Path) -> dict[str, Any]:
    output_dir = project_root / "artifacts" / "latest"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "execution.log"
    log_lines = [f"Dashboard refresh started at {datetime.now(UTC).isoformat()}\n"]
    commands = [
        [
            sys.executable,
            "-m",
            "kt_championship_engine",
            "collect",
            "--output",
            "data/snapshots/latest.json",
        ],
        [
            sys.executable,
            "-m",
            "kt_championship_engine",
            "run",
            "--snapshot",
            "data/snapshots/latest.json",
            "--config",
            "config/default.toml",
            "--output",
            "artifacts/latest",
        ],
    ]

    try:
        for command in commands:
            log_lines.append(f"\n$ {' '.join(command[2:])}\n")
            try:
                result = subprocess.run(
                    command,
                    cwd=project_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
            except subprocess.TimeoutExpired as exc:
                log_lines.append((exc.stdout or "") + (exc.stderr or ""))
                raise RefreshError("갱신 작업이 15분 제한 시간을 초과했습니다. 실행 로그를 확인하세요.") from exc
            log_lines.append(result.stdout)
            log_lines.append(result.stderr)
            if result.returncode != 0:
                raise RefreshError(
                    f"{'수집' if command[3] == 'collect' else '시뮬레이션'} 명령이 종료 코드 "
                    f"{result.returncode}로 실패했습니다. 실행 로그를 확인하세요."
                )
    finally:
        log_path.write_text("".join(log_lines), encoding="utf-8")

    return load_dashboard_state(project_root)


def serve_dashboard(project_root: Path, *, host: str, port: int) -> None:
    resolved_root = project_root.resolve()
    web_dir = Path(__file__).parent / "web"
    refresh_lock = Lock()

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "KTChampionshipDashboard/1.0"

        def do_GET(self) -> None:
            request_path = urlsplit(self.path).path
            if request_path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
                return
            if request_path == "/api/summary":
                try:
                    self._send_json(200, load_dashboard_state(resolved_root))
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    self._send_json(503, {"error": "최신 산출물을 읽을 수 없습니다. 새로고침을 실행하세요."})
                return
            if request_path == "/assets/tokens.css":
                asset_path = resolved_root / "design" / "variables.css"
                content_type = "text/css; charset=utf-8"
            else:
                asset = ASSET_FILES.get(request_path)
                if asset is None:
                    self._send_json(404, {"error": "요청한 경로를 찾을 수 없습니다."})
                    return
                asset_path = web_dir / asset[0]
                content_type = asset[1]
            try:
                self._send_bytes(200, asset_path.read_bytes(), content_type)
            except OSError:
                self._send_json(500, {"error": "대시보드 파일을 읽을 수 없습니다."})

        def do_HEAD(self) -> None:
            request_path = urlsplit(self.path).path
            if request_path == "/api/summary":
                try:
                    body = json.dumps(
                        load_dashboard_state(resolved_root), ensure_ascii=False, allow_nan=False
                    ).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                    status = 200
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    body = json.dumps({"error": "최신 산출물을 읽을 수 없습니다."}).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                    status = 503
            elif request_path == "/assets/tokens.css":
                asset_path = resolved_root / "design" / "variables.css"
                content_type = "text/css; charset=utf-8"
                status = 200
                try:
                    body = asset_path.read_bytes()
                except OSError:
                    body = b""
                    status = 500
            else:
                asset = ASSET_FILES.get(request_path)
                if asset is None:
                    self._send_json(404, {"error": "요청한 경로를 찾을 수 없습니다."}, head_only=True)
                    return
                asset_path = web_dir / asset[0]
                content_type = asset[1]
                status = 200
                try:
                    body = asset_path.read_bytes()
                except OSError:
                    body = b""
                    status = 500
            self._send_bytes(status, body, content_type, head_only=True)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/refresh":
                self._send_json(404, {"error": "요청한 경로를 찾을 수 없습니다."})
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                self._send_json(403, {"error": "다른 사이트에서 보낸 갱신 요청은 허용되지 않습니다."})
                return
            if not refresh_lock.acquire(blocking=False):
                self._send_json(409, {"error": "이미 갱신 작업이 진행 중입니다."})
                return
            try:
                state = refresh_dashboard_data(resolved_root)
                self._send_json(200, state)
            except (RefreshError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._send_json(502, {"error": str(exc)})
            finally:
                refresh_lock.release()

        def _send_json(self, status: int, payload: dict[str, Any], *, head_only: bool = False) -> None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8", head_only=head_only)

        def _send_bytes(self, status: int, body: bytes, content_type: str, *, head_only: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            policy = (
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'"
            )
            self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.log_date_time_string()} {format % args}")

    try:
        server = ThreadingHTTPServer((host, port), DashboardHandler)
    except OSError as exc:
        raise RefreshError(f"대시보드 주소 {host}:{port}를 열지 못했습니다: {exc}") from exc
    print(f"KT Championship Engine dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard server stopped.")
    finally:
        server.server_close()
