from __future__ import annotations

from pathlib import Path
import sys
import unittest


E2E_ROOT = Path(__file__).resolve().parents[1] / "tests" / "e2e"
if str(E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(E2E_ROOT))

from lapis_anki_e2e.fixture_builder import load_base_lapis_assets
from lapis_anki_e2e.fixture_data import build_stub_lookup_results


class E2eFixtureDataTest(unittest.TestCase):
    def test_base_lapis_assets_strip_lookup(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fields, _front, back, css = load_base_lapis_assets(repo_root)

        self.assertNotIn("KanjiLookupData", [field["name"] for field in fields])
        self.assertNotIn("lapis-lookup-v1", back)
        self.assertNotIn("lapis-lookup-v1", css)

    def test_stub_results_include_payloads_and_legacy_generated_fields(self) -> None:
        addon = type(
            "FakeAddon",
            (),
            {"LEGACY_CONVERT_MODE": "convertLegacy", "LOOKUP_ONLY_MODE": "lookupOnly"},
        )
        results = build_stub_lookup_results(
            addon,
            [
                {"noteId": 1, "mode": addon.LOOKUP_ONLY_MODE, "expression": "粒子"},
                {"noteId": 2, "mode": addon.LEGACY_CONVERT_MODE, "expression": "銀貨"},
            ],
        )

        self.assertEqual(len(results["results"]), 2)
        self.assertNotIn("generatedFields", results["results"][0])
        self.assertIn("generatedFields", results["results"][1])
        self.assertIn("sharedTerms", results["results"][0])
        self.assertEqual(results["results"][1]["payload"]["expression"], "銀貨")


if __name__ == "__main__":
    unittest.main()
