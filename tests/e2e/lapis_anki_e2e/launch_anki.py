from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

from aqt.profiles import ProfileManager


DRIVER_ADDON_NAME = "lapis_e2e_driver"
LOOKUP_ADDON_NAME = "lapis_lookup"
PROFILE_NAME = "lapis-e2e"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch Anki for the Lapis lookup E2E harness.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--fixture-path", required=True)
    return parser.parse_args()


def ensure_symlink(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.symlink_to(source, target_is_directory=True)


def ensure_profile(base_dir: Path) -> None:
    manager = ProfileManager(base=base_dir)
    manager.setupMeta()
    manager.create(PROFILE_NAME)


def ensure_sys_path(path: Path) -> None:
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    fixture_path = Path(args.fixture_path).resolve()
    base_dir = artifacts_dir / "anki-base"
    addons_dir = base_dir / "addons21"
    addons_dir.mkdir(parents=True, exist_ok=True)
    ensure_profile(base_dir)

    ensure_symlink(repo_root / "anki_addon" / LOOKUP_ADDON_NAME, addons_dir / LOOKUP_ADDON_NAME)
    ensure_symlink(repo_root / "tests" / "e2e" / "addons" / DRIVER_ADDON_NAME, addons_dir / DRIVER_ADDON_NAME)

    env = os.environ.copy()
    env.update(
        {
            "ANKI_BASE": str(base_dir),
            "LAPIS_E2E_REPO_ROOT": str(repo_root),
            "LAPIS_E2E_ARTIFACTS": str(artifacts_dir),
            "LAPIS_E2E_FIXTURE": str(fixture_path),
            "LAPIS_E2E_PYTHONPATH": str(repo_root / "tests" / "e2e"),
            "LAPIS_E2E_DRIVER": "1",
            "LAPIS_E2E_REPORT": str(artifacts_dir / "report.json"),
            "LAPIS_E2E_DEBUG_WEBVIEW": os.environ.get("LAPIS_E2E_DEBUG_WEBVIEW", ""),
            "LAPIS_E2E_DEBUG_PORT": os.environ.get("LAPIS_E2E_DEBUG_PORT", ""),
            "LAPIS_E2E_DEBUG_PAUSE_AT": os.environ.get("LAPIS_E2E_DEBUG_PAUSE_AT", ""),
            "LAPIS_E2E_DEBUG_KEEP_OPEN": os.environ.get("LAPIS_E2E_DEBUG_KEEP_OPEN", ""),
            "LAPIS_E2E_DEBUG_DEVTOOLS_URL": os.environ.get("LAPIS_E2E_DEBUG_DEVTOOLS_URL", ""),
            "LAPIS_E2E_PREVIEW_ORDER": os.environ.get("LAPIS_E2E_PREVIEW_ORDER", "lapis-first"),
        }
    )
    os.environ.update(env)

    ensure_sys_path(repo_root / "anki_addon")
    ensure_sys_path(repo_root / "tests" / "e2e")

    result_code = 0
    try:
        from lapis_anki_e2e.driver import init_driver
        from lapis_lookup import addon as lookup_addon
        from aqt import run as run_anki

        lookup_addon.init()
        init_driver()
        sys.argv = [
            "anki",
            "--base",
            str(base_dir),
            "--profile",
            PROFILE_NAME,
            "--lang",
            "en",
        ]
        result_code = int(run_anki() or 0)
    except SystemExit as error:
        result_code = int(error.code or 0)
    except Exception:
        traceback.print_exc()
        result_code = 1

    report_path = artifacts_dir / "report.json"
    if not report_path.exists():
        report = {
            "status": "failed",
            "reason": "Anki exited before the driver wrote a report.",
            "anki": {
                "returnCode": result_code,
            },
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
