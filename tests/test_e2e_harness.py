from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "tests" / "e2e" / "run_anki_lookup_e2e.py"
E2E_ROOT = REPO_ROOT / "tests" / "e2e"
if str(E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(E2E_ROOT))

from lapis_anki_e2e.debug_config import DEFAULT_DEBUG_PORT, parse_pause_at


def load_harness_module():
    spec = importlib.util.spec_from_file_location("run_anki_lookup_e2e", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestE2EHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_harness_module()

    def test_parse_pause_at_deduplicates_and_preserves_order(self) -> None:
        self.assertEqual(
            parse_pause_at("after-preview-render, after-preview-render,after-kanji-click"),
            ["after-preview-render", "after-kanji-click"],
        )

    def test_parse_args_accepts_debug_flags(self) -> None:
        args = self.module.parse_args(
            [
                "--debug-webview",
                "--debug-port",
                "9444",
                "--pause-at",
                "after-preview-render,after-kanji-click",
                "--debug-keep-open",
            ]
        )
        self.assertTrue(args.debug_webview)
        self.assertEqual(args.debug_port, 9444)
        self.assertEqual(
            args.pause_at_phases,
            ["after-preview-render", "after-kanji-click"],
        )
        self.assertTrue(args.debug_keep_open)

    def test_parse_args_uses_default_debug_port(self) -> None:
        args = self.module.parse_args(["--debug-webview"])
        self.assertEqual(args.debug_port, DEFAULT_DEBUG_PORT)
        self.assertEqual(args.pause_at_phases, [])

    def test_build_docker_command_includes_debug_env_and_port(self) -> None:
        artifacts_dir = Path("/tmp/lapis-e2e-test-artifacts")
        command = self.module.build_docker_command(
            docker="/usr/bin/docker",
            image="example:test",
            platform="linux/amd64",
            artifacts_dir=artifacts_dir,
            debug_webview=True,
            debug_port=9333,
            pause_at_phases=["after-preview-render", "after-kanji-click"],
            debug_keep_open=True,
            preview_order="legacy-first",
            cidfile=artifacts_dir / "container.cid",
        )
        self.assertIn("--cidfile", command)
        self.assertIn(str(artifacts_dir / "container.cid"), command)
        self.assertIn("--platform", command)
        self.assertIn("linux/amd64", command)
        self.assertIn("-p", command)
        self.assertIn("9333:9333", command)
        self.assertIn("LAPIS_E2E_DEBUG_WEBVIEW=1", command)
        self.assertIn("LAPIS_E2E_DEBUG_PORT=9333", command)
        self.assertIn(
            "LAPIS_E2E_DEBUG_PAUSE_AT=after-preview-render,after-kanji-click",
            command,
        )
        self.assertIn("LAPIS_E2E_DEBUG_KEEP_OPEN=1", command)
        self.assertIn("QTWEBENGINE_REMOTE_DEBUGGING=9333", command)
        self.assertIn(
            "QTWEBENGINE_CHROMIUM_FLAGS=--remote-debugging-address=0.0.0.0 --remote-allow-origins=*",
            command,
        )
        self.assertIn("LAPIS_E2E_PREVIEW_ORDER=legacy-first", command)
        self.assertIn(f"{artifacts_dir}:/artifacts", command)

    def test_parse_args_accepts_preview_order_and_timeout(self) -> None:
        args = self.module.parse_args(
            ["--preview-order", "legacy-first", "--timeout", "12"]
        )
        self.assertEqual(args.preview_order, "legacy-first")
        self.assertEqual(args.timeout, 12)

    def test_parse_args_accepts_platform(self) -> None:
        args = self.module.parse_args(["--platform", "linux/amd64"])
        self.assertEqual(args.platform, "linux/amd64")


if __name__ == "__main__":
    unittest.main()
