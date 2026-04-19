import json
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_ROOT / "apps" / "dsa-desktop" / "scripts" / "smoke.js"


def _write_desktop_fixture(tmp_path: Path, *, extra_resources: list[dict[str, str]]) -> Path:
    app_root = tmp_path / "apps" / "dsa-desktop"
    scripts_dir = app_root / "scripts"
    renderer_dir = app_root / "renderer"
    scripts_dir.mkdir(parents=True)
    renderer_dir.mkdir(parents=True)

    shutil.copy2(SMOKE_SCRIPT, scripts_dir / "smoke.js")
    (app_root / "main.js").write_text("// main", encoding="utf-8")
    (app_root / "preload.js").write_text("// preload", encoding="utf-8")
    (renderer_dir / "loading.html").write_text("<html></html>", encoding="utf-8")

    package_json = {
        "name": "daily-stock-analysis-desktop",
        "private": True,
        "main": "main.js",
        "build": {
            "files": [
                "main.js",
                "preload.js",
                "renderer/**/*",
            ],
            "extraResources": extra_resources,
        },
    }
    (app_root / "package.json").write_text(
        json.dumps(package_json, indent=2),
        encoding="utf-8",
    )
    return app_root


def _run_smoke(app_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "scripts/smoke.js"],
        cwd=app_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_desktop_smoke_fails_when_required_extra_resource_is_missing(tmp_path: Path) -> None:
    app_root = _write_desktop_fixture(
        tmp_path,
        extra_resources=[
            {
                "from": "../../.env.example",
                "to": ".env.example",
            }
        ],
    )

    result = _run_smoke(app_root)

    assert result.returncode != 0
    assert "extraResources is missing required entry" in (result.stdout + result.stderr)


def test_desktop_smoke_passes_with_required_extra_resources_declared(tmp_path: Path) -> None:
    app_root = _write_desktop_fixture(
        tmp_path,
        extra_resources=[
            {
                "from": "../../.env.example",
                "to": ".env.example",
            },
            {
                "from": "../../dist/backend/stock_analysis",
                "to": "backend/stock_analysis",
            },
        ],
    )

    result = _run_smoke(app_root)

    assert result.returncode == 0
    assert "desktop smoke OK" in result.stdout
