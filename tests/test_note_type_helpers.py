from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "anki_addon"
    / "lapis_lookup"
    / "note_type_helpers.py"
)
SPEC = importlib.util.spec_from_file_location("note_type_helpers", MODULE_PATH)
assert SPEC and SPEC.loader
note_type_helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(note_type_helpers)


class NoteTypeHelpersTest(unittest.TestCase):
    def test_normalize_sort_field_text_strips_html(self) -> None:
        value = note_type_helpers.normalize_sort_field_text(" <div>猫&nbsp;<b>です</b></div> ")
        self.assertEqual(value, "猫 です")

    def test_partition_lapis_detection(self) -> None:
        model = {
            "flds": [
                {"name": "Expression"},
                {"name": "ExpressionFurigana"},
                {"name": "MainDefinition"},
                {"name": "Glossary"},
                {"name": "Sentence"},
                {"name": "FreqSort"},
            ]
        }
        self.assertTrue(note_type_helpers.is_lapis_model(model))

    def test_build_legacy_field_map_targets_expression_only(self) -> None:
        old_model = {
            "sortf": 2,
            "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "Sort"}],
            "tmpls": [{"name": "Card 1"}],
        }
        new_model = {
            "flds": [
                {"name": "Expression"},
                {"name": "ExpressionFurigana"},
                {"name": "KanjiLookupData"},
            ]
        }
        self.assertEqual(
            note_type_helpers.build_legacy_field_map(old_model, new_model),
            {2: 0},
        )

    def test_build_lookup_field_map_matches_by_name(self) -> None:
        old_model = {
            "flds": [{"name": "Expression"}, {"name": "Glossary"}],
            "tmpls": [{"name": "Mining"}],
        }
        new_model = {
            "flds": [
                {"name": "Expression"},
                {"name": "ExpressionFurigana"},
                {"name": "Glossary"},
                {"name": "KanjiLookupData"},
            ],
            "tmpls": [{"name": "Mining"}],
        }
        self.assertEqual(
            note_type_helpers.build_lookup_field_map(old_model, new_model),
            {0: 0, 1: 2},
        )


if __name__ == "__main__":
    unittest.main()
