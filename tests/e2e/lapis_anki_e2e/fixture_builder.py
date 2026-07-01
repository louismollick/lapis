from __future__ import annotations

from pathlib import Path


LOOKUP_FIELD_NAME = "KanjiLookupData"
LOOKUP_CSS_START = "/* lapis-lookup-v1:start */"
LOOKUP_CSS_END = "/* lapis-lookup-v1:end */"
LOOKUP_MARKUP_START = "<!-- lapis-lookup-v1:markup:start -->"
LOOKUP_MARKUP_END = "<!-- lapis-lookup-v1:markup:end -->"
LOOKUP_SCRIPT_START = "// lapis-lookup-v1:script:start"
LOOKUP_SCRIPT_END = "// lapis-lookup-v1:script:end"


def parse_lapis_fields(repo_root: Path) -> list[dict[str, object]]:
    fields_path = repo_root / "build" / "anki_fields.yaml"
    fields: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for raw_line in fields_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            if current is not None:
                fields.append(current)
            current = {}
            line = line[2:]
        if ":" not in line or current is None:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        current[key] = int(value) if value.isdigit() else value

    if current is not None:
        fields.append(current)

    return fields


def strip_lookup_css(css: str) -> str:
    return strip_marked_block(css, LOOKUP_CSS_START, LOOKUP_CSS_END).rstrip() + "\n"


def strip_lookup_template(template: str) -> str:
    stripped = strip_marked_block(template, LOOKUP_MARKUP_START, LOOKUP_MARKUP_END)
    stripped = strip_marked_block(stripped, LOOKUP_SCRIPT_START, LOOKUP_SCRIPT_END)
    return stripped.rstrip() + "\n"


def strip_marked_block(text: str, start_marker: str, end_marker: str) -> str:
    if start_marker not in text or end_marker not in text:
        return text
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    return f"{text[:start].rstrip()}\n\n{text[end:].lstrip()}"


def load_base_lapis_assets(repo_root: Path) -> tuple[list[dict[str, object]], str, str, str]:
    fields = [
        field
        for field in parse_lapis_fields(repo_root)
        if field["name"] != LOOKUP_FIELD_NAME
    ]
    front = (repo_root / "src" / "front.html").read_text(encoding="utf-8")
    back = strip_lookup_template(
        (repo_root / "src" / "back.html").read_text(encoding="utf-8")
    )
    css = strip_lookup_css(
        (repo_root / "src" / "styling.css").read_text(encoding="utf-8")
    )
    return fields, front, back, css


def ordered_field_values(
    fields: list[dict[str, object]],
    values: dict[str, str],
) -> list[str]:
    return [values.get(str(field["name"]), "") for field in fields]
