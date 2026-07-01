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
        "generated_fields": None,
        "payload": {
            "version": 2,
            "expression": "粒子",
            "kanji": [
                {"char": "粒", "wordRefs": ["粒子", "微粒子"], "components": ["米", "立"]},
                {"char": "子", "wordRefs": ["粒子"], "components": ["了", "一"]},
            ],
        },
        "shared_terms": {
            "粒子": {
                "term": "粒子",
                "reading": "りゅうし",
                "frequency": {"value": 100, "source": "JPDB"},
                "entryHtml": (
                    '<div class="yomitan-glossary"><ol>'
                    '<li data-dictionary="FixtureDict"><span>particle</span></li>'
                    "</ol></div>"
                ),
            },
            "微粒子": {
                "term": "微粒子",
                "reading": "びりゅうし",
                "frequency": {"value": 240, "source": "JPDB"},
                "entryHtml": (
                    '<div class="yomitan-glossary"><ol>'
                    '<li data-dictionary="FixtureDict"><span>fine particle</span></li>'
                    "</ol></div>"
                ),
            },
        },
        "expected": {
            "clicked_kanji": "粒",
            "components": ["米", "立"],
            "related_rows": 2,
            "frequency_source": "JPDB",
            "first_related_term": "粒子",
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
        "generated_fields": {
            "Expression": "銀貨",
            "ExpressionFurigana": "銀貨[ぎんか]",
            "ExpressionReading": "ぎんか",
            "MainDefinition": (
                '<div class="yomitan-glossary"><ol>'
                '<li data-dictionary="FixtureDict"><span>silver coin</span></li>'
                "</ol></div>"
            ),
            "Glossary": (
                '<div class="yomitan-glossary"><ol>'
                '<li data-dictionary="FixtureDict"><span>coin made of silver</span></li>'
                "</ol></div>"
            ),
            "Sentence": "古い<b>銀貨</b>が見つかった。",
            "FreqSort": "200",
            "Frequency": "<ul><li>JPDB: 200</li></ul>",
            "MiscInfo": "Fixture legacy note",
        },
        "payload": {
            "version": 2,
            "expression": "銀貨",
            "kanji": [
                {"char": "銀", "wordRefs": ["銀貨", "白銀"], "components": ["金", "艮"]},
                {"char": "貨", "wordRefs": ["貨幣"], "components": ["化", "貝"]},
            ],
        },
        "shared_terms": {
            "銀貨": {
                "term": "銀貨",
                "reading": "ぎんか",
                "frequency": {"value": 200, "source": "JPDB"},
                "entryHtml": (
                    '<div class="yomitan-glossary"><ol>'
                    '<li data-dictionary="FixtureDict"><span>silver coin</span></li>'
                    "</ol></div>"
                ),
            },
            "白銀": {
                "term": "白銀",
                "reading": "はくぎん",
                "frequency": {"value": 310, "source": "JPDB"},
                "entryHtml": (
                    '<div class="yomitan-glossary"><ol>'
                    '<li data-dictionary="FixtureDict"><span>silver</span></li>'
                    "</ol></div>"
                ),
            },
            "貨幣": {
                "term": "貨幣",
                "reading": "かへい",
                "frequency": {"value": 400, "source": "JPDB"},
                "entryHtml": (
                    '<div class="yomitan-glossary"><ol>'
                    '<li data-dictionary="FixtureDict"><span>currency</span></li>'
                    "</ol></div>"
                ),
            },
        },
        "expected": {
            "clicked_kanji": "銀",
            "components": ["金", "艮"],
            "related_rows": 2,
            "frequency_source": "JPDB",
            "first_related_term": "銀貨",
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


def expected_ui_assertions() -> dict[str, dict[str, Any]]:
    return {
        expression: deepcopy(data["expected"])
        for expression, data in NOTE_SCENARIOS.items()
    }


def build_stub_lookup_results(
    lookup_addon: Any,
    lookup_items: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in lookup_items:
        scenario = scenario_for_expression(str(item["expression"]))
        result = {
            "noteId": int(item["noteId"]),
            "mode": item["mode"],
            "status": "ok",
            "expression": str(item["expression"]),
            "payload": deepcopy(scenario["payload"]),
            "sharedTerms": deepcopy(scenario["shared_terms"]),
            "warnings": [],
        }
        if item["mode"] == lookup_addon.LEGACY_CONVERT_MODE:
            result["generatedFields"] = deepcopy(scenario["generated_fields"])
        results.append(result)
    return {"results": results}
