from __future__ import annotations

import html
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence


LOOKUP_FIELD_NAME = "KanjiLookupData"
CANONICAL_LAPIS_MODEL_NAME = "Lapis+Lookup"
LOOKUP_TEMPLATE_MARKER = "lapis-lookup-v1"
LOOKUP_PAYLOAD_PLACEHOLDER = "{{text:KanjiLookupData}}"
LEGACY_CONVERT_MODE = "convertLegacy"
LOOKUP_ONLY_MODE = "lookupOnly"
CORE_LAPIS_FIELDS = {
    "Expression",
    "ExpressionFurigana",
    "MainDefinition",
    "Glossary",
    "Sentence",
    "FreqSort",
}


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


def is_lapis_model(model: Mapping[str, Any]) -> bool:
    field_names = {field["name"] for field in model["flds"]}
    return CORE_LAPIS_FIELDS.issubset(field_names)


def is_lookup_enabled_model(model: Mapping[str, Any]) -> bool:
    field_names = {field["name"] for field in model["flds"]}
    if LOOKUP_FIELD_NAME not in field_names:
        return False
    return any(LOOKUP_TEMPLATE_MARKER in template["afmt"] for template in model["tmpls"])


def is_lookup_ready_model(model: Mapping[str, Any]) -> bool:
    if not is_lookup_enabled_model(model):
        return False
    return any(LOOKUP_PAYLOAD_PLACEHOLDER in template["afmt"] for template in model["tmpls"])


def build_lookup_field_map(old_model: Mapping[str, Any], new_model: Mapping[str, Any]) -> dict[int, int]:
    old_field_names = [field["name"] for field in old_model["flds"]]
    mapping: dict[int, int] = {}
    for old_index, field_name in enumerate(old_field_names):
        try:
            new_index = next(
                index
                for index, new_field in enumerate(new_model["flds"])
                if new_field["name"] == field_name
            )
        except StopIteration:
            continue
        mapping[old_index] = new_index
    return mapping


def build_lookup_template_map(old_model: Mapping[str, Any], new_model: Mapping[str, Any]) -> dict[int, int]:
    template_count = min(len(old_model["tmpls"]), len(new_model["tmpls"]))
    return {index: index for index in range(template_count)}


def build_legacy_field_map(
    old_model: Mapping[str, Any],
    new_model: Mapping[str, Any],
    *,
    expression_field_name: str = "Expression",
) -> dict[int, int]:
    expression_index = next(
        index
        for index, field in enumerate(new_model["flds"])
        if field["name"] == expression_field_name
    )
    return {int(old_model["sortf"]): expression_index}


def build_legacy_template_map(old_model: Mapping[str, Any]) -> dict[int, int]:
    return {0: 0} if old_model["tmpls"] else {}


def normalize_sort_field_text(raw_value: str) -> str:
    unescaped = html.unescape(raw_value or "")
    stripper = _HTMLStripper()
    stripper.feed(unescaped)
    text = stripper.get_text()
    return " ".join(text.split())


def extract_sort_field_expression(note: Any) -> str:
    model = note.note_type()
    sort_index = int(model["sortf"])
    return normalize_sort_field_text(note.fields[sort_index])


def partition_note_ids(col: Any, note_ids: Sequence[int]) -> dict[int, list[int]]:
    partitions: dict[int, list[int]] = {}
    for note_id in note_ids:
        model_id = int(col.get_note(note_id).mid)
        partitions.setdefault(model_id, []).append(note_id)
    return partitions
