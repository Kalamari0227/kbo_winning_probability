import json
from pathlib import Path

from kt_championship_engine.pages import build_pages


def test_build_pages_publishes_seed_state_with_project_relative_assets(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    data_dir = project_root / "data"
    design_dir = project_root / "design"
    snapshots_dir = data_dir / "snapshots"
    snapshots_dir.mkdir(parents=True)
    design_dir.mkdir()
    seed = {
        "summary": {"forecast_mode": "jev_adjusted", "jev_successful_game_count": 53},
        "standings": [],
        "remaining_games": [],
        "snapshot_manifest": {"source_type": "official"},
    }
    (data_dir / "pages_seed.json").write_text(json.dumps(seed), encoding="utf-8")
    (snapshots_dir / "latest.json").write_text("{}", encoding="utf-8")
    (design_dir / "variables.css").write_text(":root { --test-token: 1; }", encoding="utf-8")

    output_dir = tmp_path / "_site"
    build_pages(project_root, output_dir)

    page = (output_dir / "index.html").read_text(encoding="utf-8")
    published_state = json.loads((output_dir / "dashboard-data.json").read_text(encoding="utf-8"))
    dashboard_js = (output_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")

    assert 'content="dashboard-data.json" data-mode="published"' in page
    assert '<link rel="icon" type="image/png" href="assets/teams/KT.png">' in page
    assert 'href="assets/dashboard.css"' in page
    assert '<button class="refresh-button" id="refresh-button" type="button" hidden>' in page
    assert "refresh-workflow-link" not in page
    assert published_state == seed
    tokens = (output_dir / "assets" / "tokens.css").read_text(encoding="utf-8")
    source_tokens = design_dir.joinpath("variables.css").read_text(encoding="utf-8")
    assert tokens == source_tokens
    assert (output_dir / "assets" / "teams" / "KT.png").is_file()
    assert 'new URL(`assets/teams/${team}.png`, document.baseURI)' in dashboard_js
    assert (output_dir / ".nojekyll").is_file()
