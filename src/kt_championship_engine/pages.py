from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .web_server import load_dashboard_state


def build_pages(project_root: Path, output_dir: Path) -> str:
    state, state_source = _load_publish_state(project_root)
    web_dir = Path(__file__).parent / "web"
    assets_dir = output_dir / "assets"
    teams_dir = assets_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    html = (web_dir / "index.html").read_text(encoding="utf-8")
    dynamic_state_marker = 'content="/api/summary" data-mode="dynamic"'
    if dynamic_state_marker not in html:
        raise ValueError("dashboard data URL marker is missing from web/index.html")
    html = html.replace(dynamic_state_marker, 'content="dashboard-data.json" data-mode="published"')
    html = html.replace("경기 후 공식 결과로 재계산", "매일 오전 2시 자동 재계산")
    (output_dir / "index.html").write_text(html, encoding="utf-8")

    shutil.copy2(web_dir / "dashboard.css", assets_dir / "dashboard.css")
    shutil.copy2(web_dir / "dashboard.js", assets_dir / "dashboard.js")
    shutil.copy2(project_root / "design" / "variables.css", assets_dir / "tokens.css")
    for emblem in (web_dir / "teams").glob("*.png"):
        shutil.copy2(emblem, teams_dir / emblem.name)

    (output_dir / "dashboard-data.json").write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").touch()
    return state_source


def _load_publish_state(project_root: Path) -> tuple[dict[str, Any], str]:
    summary_path = project_root / "artifacts" / "latest" / "simulation_summary.json"
    snapshot_path = project_root / "data" / "snapshots" / "latest.json"
    if summary_path.is_file():
        if not snapshot_path.is_file():
            raise ValueError("latest simulation artifacts exist but the matching snapshot is missing")
        return load_dashboard_state(project_root), "artifacts/latest"

    seed_path = project_root / "data" / "pages_seed.json"
    if not seed_path.is_file() and snapshot_path.is_file():
        raise ValueError("latest snapshot exists without simulation artifacts or a Pages seed")
    with seed_path.open("r", encoding="utf-8") as stream:
        return json.load(stream), str(seed_path.relative_to(project_root))
