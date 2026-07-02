from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_RUNTIME_IMAGE = "ghcr.io/louismollick/minimal-anki-desktop-docker:sha-dc61864"
DEFAULT_RUNTIME_PLATFORM = "linux/amd64"
FIXTURE_PACKAGE_NAME = "lapis_lookup_e2e.apkg"
FIXTURE_DECK_NAME = "Lapis Lookup E2E"
LAPIS_MODEL_NAME = "Lapis"
LEGACY_MODEL_NAME = "Legacy Mining"
CANONICAL_MODEL_NAME = "Lapis+Lookup"


NOTE_SCENARIOS: dict[str, dict[str, Any]] = {
    "粒子": {
        "label": "lapis",
        "source_model": LAPIS_MODEL_NAME,
        "lapis_fields": {
            "Expression": "粒子",
            "ExpressionFurigana": "粒子[りゅうし]",
            "ExpressionReading": "りゅうし",
            "SelectionText": "",
            "MainDefinition": (
                '<div class="yomitan-glossary"><ol>'
                '<li data-dictionary="FixtureDict"><span>particle</span></li>'
                "</ol></div>"
            ),
            "DefinitionPicture": "",
            "Sentence": "この<b>粒子</b>は安定している。",
            "SentenceFurigana": "",
            "SentenceAudio": "",
            "Picture": "",
            "Glossary": (
                '<div class="yomitan-glossary"><ol>'
                '<li data-dictionary="FixtureDict"><span>tiny particle</span></li>'
                "</ol></div>"
            ),
            "Hint": "",
            "IsWordAndSentenceCard": "",
            "IsClickCard": "",
            "IsSentenceCard": "",
            "IsAudioCard": "",
            "PitchPosition": "",
            "PitchCategories": "",
            "Frequency": "<ul><li>JPDB: 100</li></ul>",
            "FreqSort": "100",
            "MiscInfo": "Fixture Lapis note",
        },
    },
    "銀貨": {
        "label": "legacy",
        "source_model": LEGACY_MODEL_NAME,
        "legacy_fields": {
            "Front": "銀貨",
            "Back": "<div>legacy fixture</div>",
            "Sort": "銀貨",
        },
    },
}


def scenario_for_expression(expression: str) -> dict[str, Any]:
    try:
        return deepcopy(NOTE_SCENARIOS[expression])
    except KeyError as error:
        raise KeyError(f"Unsupported E2E expression: {expression}") from error


def base_lapis_note_fields() -> dict[str, str]:
    return deepcopy(NOTE_SCENARIOS["粒子"]["lapis_fields"])


def legacy_note_fields() -> dict[str, str]:
    return deepcopy(NOTE_SCENARIOS["銀貨"]["legacy_fields"])

