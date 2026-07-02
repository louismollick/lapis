from __future__ import annotations

from pathlib import Path
import sys
import unittest


E2E_ROOT = Path(__file__).resolve().parents[1] / "tests" / "e2e"
if str(E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(E2E_ROOT))

from lapis_anki_e2e.fixture_builder import load_base_lapis_assets


class E2eFixtureDataTest(unittest.TestCase):
    def test_base_lapis_assets_strip_lookup(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fields, _front, back, css = load_base_lapis_assets(repo_root)

        self.assertNotIn("KanjiLookupData", [field["name"] for field in fields])
        self.assertNotIn("lapis-lookup-v1", back)
        self.assertNotIn("lapis-lookup-v1", css)


if __name__ == "__main__":
    unittest.main()
