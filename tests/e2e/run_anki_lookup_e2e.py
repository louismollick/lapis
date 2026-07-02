from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_ROOT = Path(__file__).resolve().parent
if str(E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(E2E_ROOT))

from lapis_anki_e2e.fixture_data import (
    DEFAULT_RUNTIME_IMAGE,
    DEFAULT_RUNTIME_PLATFORM,
    FIXTURE_PACKAGE_NAME,
)
from lapis_anki_e2e.debug_config import (
    DEBUG_CONTINUE_FILE_NAME,
    DEFAULT_DEBUG_PORT,
    devtools_url,
    parse_pause_at,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Lapis lookup Anki E2E harness.")
    parser.add_argument("--image", default=None, help="Container image override.")
    parser.add_argument(
        "--platform",
        default=None,
        help="Container platform override, e.g. linux/amd64.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Directory to store report/screenshot/DOM artifacts.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Preserve the artifact directory even on success.",
    )
    parser.add_argument(
        "--debug-webview",
        action="store_true",
        help="Expose Qt WebEngine remote debugging and keep the run inspectable.",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=DEFAULT_DEBUG_PORT,
        help="Remote debugging port to expose when --debug-webview is enabled.",
    )
    parser.add_argument(
        "--pause-at",
        default=None,
        help="Comma-separated debug pause phases.",
    )
    parser.add_argument(
        "--debug-keep-open",
        action="store_true",
        help="Pause before exit in debug mode until resumed manually.",
    )
    parser.add_argument(
        "--preview-order",
        choices=("lapis-first", "legacy-first"),
        default="lapis-first",
        help="Order to preview converted cards; useful for isolating previewer state leaks.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="Maximum seconds to allow the container run before failing.",
    )
    args = parser.parse_args(argv)
    if args.debug_port <= 0:
        parser.error("--debug-port must be a positive integer")
    if args.timeout <= 0:
        parser.error("--timeout must be a positive integer")
    if (args.pause_at or args.debug_keep_open) and not args.debug_webview:
        parser.error("--pause-at and --debug-keep-open require --debug-webview")
    try:
        args.pause_at_phases = parse_pause_at(args.pause_at)
    except ValueError as error:
        parser.error(str(error))
    return args


def ensure_docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("docker not found on PATH")
    return docker


def reset_artifacts_dir(artifacts_dir: Path) -> None:
    paths_to_remove = [
        artifacts_dir / "anki-base",
        artifacts_dir / "report.json",
        artifacts_dir / "container.cid",
        artifacts_dir / "lapis-failure.png",
        artifacts_dir / "lapis-failure.html",
        artifacts_dir / "legacy-failure.png",
        artifacts_dir / "legacy-failure.html",
    ]
    for path in paths_to_remove:
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def build_docker_command(
    *,
    docker: str,
    image: str,
    platform: str | None,
    artifacts_dir: Path,
    debug_webview: bool,
    debug_port: int,
    pause_at_phases: list[str],
    debug_keep_open: bool,
    preview_order: str,
    cidfile: Path | None = None,
) -> list[str]:
    command = [
        docker,
        "run",
        "--rm",
    ]
    if cidfile is not None:
        command.extend(["--cidfile", str(cidfile)])
    if platform:
        command.extend(["--platform", platform])
    command.extend(
        [
            "-e",
            "LAPIS_E2E_ARTIFACTS=/artifacts",
            "-e",
            f"LAPIS_E2E_FIXTURE=/workdir/tests/e2e/fixtures/{FIXTURE_PACKAGE_NAME}",
            "-e",
            "LAPIS_E2E_PYTHONPATH=/workdir/tests/e2e",
            "-e",
            "LAPIS_E2E_DRIVER=1",
            "-e",
            "LIBGL_ALWAYS_SOFTWARE=1",
            "-e",
            "QT_OPENGL=software",
            "-e",
            "QT_QUICK_BACKEND=software",
            "-e",
            "QT_XCB_GL_INTEGRATION=",
            "-e",
            f"LAPIS_E2E_PREVIEW_ORDER={preview_order}",
        ]
    )
    if debug_webview:
        command.extend(
            [
                "-e",
                "LAPIS_E2E_DEBUG_WEBVIEW=1",
                "-e",
                f"LAPIS_E2E_DEBUG_PORT={debug_port}",
                "-e",
                f"LAPIS_E2E_DEBUG_PAUSE_AT={','.join(pause_at_phases)}",
                "-e",
                f"LAPIS_E2E_DEBUG_DEVTOOLS_URL={devtools_url(debug_port)}",
                "-e",
                f"QTWEBENGINE_REMOTE_DEBUGGING={debug_port}",
                "-e",
                "QTWEBENGINE_CHROMIUM_FLAGS=--remote-debugging-address=0.0.0.0 --remote-allow-origins=*",
                "-p",
                f"{debug_port}:{debug_port}",
            ]
        )
        if debug_keep_open:
            command.extend(["-e", "LAPIS_E2E_DEBUG_KEEP_OPEN=1"])

    command.extend(
        [
            "-v",
            f"{REPO_ROOT}:/workdir:ro",
            "-v",
            "/workdir/tools/lookup/node_modules",
            "-v",
            f"{artifacts_dir}:/artifacts",
            image,
            "python3",
            "/workdir/tests/e2e/lapis_anki_e2e/launch_anki.py",
            "--repo-root",
            "/workdir",
            "--artifacts-dir",
            "/artifacts",
            "--fixture-path",
            f"/workdir/tests/e2e/fixtures/{FIXTURE_PACKAGE_NAME}",
        ]
    )
    return command


def remove_container_from_cidfile(docker: str, cidfile: Path) -> None:
    try:
        container_id = cidfile.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return
    if not container_id:
        return
    subprocess.run(
        [docker, "rm", "-f", container_id],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )


def main() -> int:
    args = parse_args()
    docker = ensure_docker()
    image = args.image or os.environ.get("LAPIS_ANKI_E2E_IMAGE") or DEFAULT_RUNTIME_IMAGE
    platform = (
        args.platform
        or os.environ.get("LAPIS_ANKI_E2E_PLATFORM")
        or DEFAULT_RUNTIME_PLATFORM
    )
    artifacts_dir = (
        Path(args.artifacts_dir).resolve()
        if args.artifacts_dir
        else Path(tempfile.mkdtemp(prefix="lapis-anki-e2e-"))
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reset_artifacts_dir(artifacts_dir)
    keep_artifacts = args.keep_artifacts or args.debug_webview
    cidfile = artifacts_dir / "container.cid"

    fixture_path = REPO_ROOT / "tests" / "e2e" / "fixtures" / FIXTURE_PACKAGE_NAME
    if not fixture_path.exists():
        raise SystemExit(f"Missing fixture package: {fixture_path}")

    command = build_docker_command(
        docker=docker,
        image=image,
        platform=platform,
        artifacts_dir=artifacts_dir,
        debug_webview=args.debug_webview,
        debug_port=args.debug_port,
        pause_at_phases=args.pause_at_phases,
        debug_keep_open=args.debug_keep_open,
        preview_order=args.preview_order,
        cidfile=cidfile,
    )

    print(f"Running Lapis lookup E2E in {image}")
    if args.debug_webview:
        continue_file = artifacts_dir / DEBUG_CONTINUE_FILE_NAME
        print(f"DevTools: {devtools_url(args.debug_port)}")
        print(f"Continue paused runs with: touch {continue_file}")
    try:
        process = subprocess.Popen(command)
        try:
            return_code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            remove_container_from_cidfile(docker, cidfile)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            print(f"E2E timed out after {args.timeout}s")
            return_code = 124
    except OSError as error:
        print(f"Failed to start E2E container: {error}")
        return_code = 125

    report_path = artifacts_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        status = report.get("status", "unknown")
        print(f"Report: {report_path}")
        print(f"Status: {status}")
        for label, note_report in report.get("notes", {}).items():
            preview = note_report.get("preview", {})
            print(
                f"{label}: model={note_report.get('models', {}).get('after', {}).get('name')} "
                f"targets={preview.get('targetCount')} "
                f"clickedKanji={preview.get('clickedKanji')}"
            )
        if return_code == 0 and status == "ok":
            if not keep_artifacts and not args.artifacts_dir:
                shutil.rmtree(artifacts_dir, ignore_errors=True)
            return 0

    print(f"Artifacts kept at {artifacts_dir}")
    return return_code or 1


if __name__ == "__main__":
    raise SystemExit(main())
