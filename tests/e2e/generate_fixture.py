from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_ROOT = Path(__file__).resolve().parent
if str(E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(E2E_ROOT))

from lapis_anki_e2e.fixture_builder import load_base_lapis_assets, ordered_field_values
from lapis_anki_e2e.fixture_data import (
    FIXTURE_DECK_NAME,
    FIXTURE_PACKAGE_NAME,
    LAPIS_MODEL_NAME,
    LEGACY_MODEL_NAME,
    base_lapis_note_fields,
    legacy_note_fields,
)

try:
    import genanki
except ModuleNotFoundError as error:
    raise SystemExit(
        "genanki is required to regenerate the E2E fixture. "
        "Install build/requirements.txt first."
    ) from error


LAPIS_MODEL_ID = 1867218449001
LEGACY_MODEL_ID = 1867218449002
DECK_ID = 1867218449003


def build_lapis_model() -> genanki.Model:
    fields, front, back, css = load_base_lapis_assets(REPO_ROOT)
    return genanki.Model(
        LAPIS_MODEL_ID,
        LAPIS_MODEL_NAME,
        fields=[{key: value for key, value in field.items() if key in {"name", "font", "size"}} for field in fields],
        templates=[{"name": "Mining", "qfmt": front, "afmt": back}],
        css=css,
    )


def build_legacy_model() -> genanki.Model:
    return genanki.Model(
        LEGACY_MODEL_ID,
        LEGACY_MODEL_NAME,
        fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Sort"}],
        templates=[{"name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{Front}}<hr>{{Back}}"}],
        sort_field_index=2,
        css=".card { font-family: sans-serif; }",
    )


def build_package() -> genanki.Package:
    lapis_model = build_lapis_model()
    legacy_model = build_legacy_model()
    fields, _front, _back, _css = load_base_lapis_assets(REPO_ROOT)

    deck = genanki.Deck(DECK_ID, FIXTURE_DECK_NAME)
    deck.add_note(
        genanki.Note(
            model=lapis_model,
            fields=ordered_field_values(fields, base_lapis_note_fields()),
            guid="lapis-e2e-lapis",
            tags=["lapis-e2e", "source:lapis"],
        )
    )
    legacy_values = legacy_note_fields()
    deck.add_note(
        genanki.Note(
            model=legacy_model,
            fields=[legacy_values["Front"], legacy_values["Back"], legacy_values["Sort"]],
            guid="lapis-e2e-legacy",
            tags=["lapis-e2e", "source:legacy"],
        )
    )

    return genanki.Package(deck)


def main() -> None:
    output_path = REPO_ROOT / "tests" / "e2e" / "fixtures" / FIXTURE_PACKAGE_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_package().write_to_file(str(output_path))
    print(output_path)


if __name__ == "__main__":
    main()
