from __future__ import annotations

import glob
import html
import json
import os
import copy
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu, qconnect
from aqt.utils import showInfo, showWarning, tooltip

from .generated_lookup_assets import (
    BACK_TEMPLATE,
    FRONT_TEMPLATE,
    LAPIS_FIELDS,
    STYLING_CSS,
    LOOKUP_CSS_BLOCK,
    LOOKUP_MARKUP_BLOCK,
    LOOKUP_SCRIPT_BLOCK,
)
from .note_type_helpers import (
    CANONICAL_LAPIS_MODEL_NAME,
    LEGACY_CONVERT_MODE,
    LOOKUP_TEMPLATE_MARKER,
    LOOKUP_FIELD_NAME,
    LOOKUP_ONLY_MODE,
    build_legacy_field_map,
    build_legacy_template_map,
    build_lookup_field_map,
    build_lookup_template_map,
    extract_sort_field_expression,
    is_lapis_model,
    is_lookup_enabled_model,
    partition_note_ids,
)

ADDON_NAME = __name__.split(".")[0]


@dataclass
class BackfillSummary:
    processed: int
    converted: int
    skipped: int
    warnings: list[str]


def init() -> None:
    gui_hooks.browser_menus_did_init.append(add_browser_menu)


def add_browser_menu(browser: Browser) -> None:
    menu = QMenu("Lapis Lookup", browser)
    menu.menuAction().setMenuRole(QAction.MenuRole.NoRole)
    browser.form.menubar.addMenu(menu)

    setup_action = QAction("Setup + Backfill Selected Notes", browser)
    setup_action.setMenuRole(QAction.MenuRole.NoRole)
    qconnect(setup_action.triggered, lambda: setup_and_backfill_selected_notes(browser))
    menu.addAction(setup_action)

    diagnose_action = QAction("Diagnose Selected Notes", browser)
    diagnose_action.setMenuRole(QAction.MenuRole.NoRole)
    qconnect(diagnose_action.triggered, lambda: diagnose_selected_notes(browser))
    menu.addAction(diagnose_action)


def setup_and_backfill_selected_notes(browser: Browser) -> None:
    note_ids = list(browser.selected_notes())
    if not note_ids:
        showWarning("Select at least one note in Browse first.", parent=browser)
        return

    config = load_config()

    QueryOp(
        parent=browser,
        op=lambda col: run_setup_and_backfill(col, note_ids, config),
        success=lambda summary: on_backfill_success(browser, summary),
    ).with_progress("Setting up lookup model and backfilling notes...").run_in_background()


def diagnose_selected_notes(browser: Browser) -> None:
    note_ids = list(browser.selected_notes())
    if not note_ids:
        showWarning("Select at least one note in Browse first.", parent=browser)
        return

    notes = [mw.col.get_note(note_id) for note_id in note_ids[:5]]
    lines: list[str] = []
    for note in notes:
        model = note.note_type()
        field_names = {field["name"] for field in model["flds"]}
        has_lookup_field = LOOKUP_FIELD_NAME in field_names
        template_marked = any(LOOKUP_TEMPLATE_MARKER in template["afmt"] for template in model["tmpls"])
        payload_length = len(note[LOOKUP_FIELD_NAME]) if has_lookup_field else 0
        lines.extend(
            [
                f"Note ID: {note.id}",
                f"Notetype: {model['name']}",
                f"Lookup field exists: {'yes' if has_lookup_field else 'no'}",
                f"Lookup template active: {'yes' if template_marked else 'no'}",
                f"Lookup payload length: {payload_length}",
                "",
            ]
        )

    showInfo("\n".join(lines).strip(), parent=browser)


def run_setup_and_backfill(col: Any, note_ids: Sequence[int], config: dict[str, Any]) -> BackfillSummary:
    results = run_lookup_cli(config, note_ids, col)
    warnings: list[str] = []
    processed = 0
    converted = 0
    skipped = 0
    canonical_model = None

    for item in results.get("results", []):
        note_id = item["noteId"]
        mode = item.get("mode", LOOKUP_ONLY_MODE)
        status = item.get("status", "ok")
        warnings.extend(item.get("warnings", []))

        if status != "ok":
            skipped += 1
            continue

        note = col.get_note(note_id)
        if mode == LEGACY_CONVERT_MODE:
            if canonical_model is None:
                canonical_model = ensure_canonical_lookup_model(col)
            convert_legacy_notes_to_model(
                col,
                [note_id],
                note.note_type(),
                canonical_model,
            )
            note = col.get_note(note_id)
            write_generated_fields(note, item.get("generatedFields", {}))
            converted += 1
        elif LOOKUP_FIELD_NAME not in note:
            ensure_lookup_model_for_notes(col, [note_id])
            note = col.get_note(note_id)

        if LOOKUP_FIELD_NAME not in note or "payload" not in item:
            skipped += 1
            warnings.append(f"Skipped note {note_id}: lookup payload unavailable after setup.")
            continue

        serialized_payload = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
        note[LOOKUP_FIELD_NAME] = html.escape(serialized_payload, quote=False)
        col.update_note(note, skip_undo_entry=True)
        processed += 1

    return BackfillSummary(
        processed=processed,
        converted=converted,
        skipped=skipped,
        warnings=warnings,
    )


def on_backfill_success(browser: Browser, summary: BackfillSummary) -> None:
    browser.search()
    message = f"Processed {summary.processed} note(s)"
    if summary.converted:
        message += f", converted {summary.converted}"
    if summary.skipped:
        message += f", skipped {summary.skipped}"
    tooltip(message, parent=browser)

    if summary.warnings:
        showInfo("\n".join(summary.warnings[:50]), parent=browser)


def ensure_lookup_model_for_notes(col: Any, note_ids: Sequence[int]) -> None:
    for model_id, model_note_ids in partition_note_ids(col, note_ids).items():
        model = col.models.get(model_id)
        if not is_lapis_model(model):
            continue
        if is_lookup_enabled_model(model):
            refresh_lookup_model(col, model)
            continue
        target_model = clone_lookup_model(col, model)
        convert_notes_to_model(col, model_note_ids, model, target_model)


def clone_lookup_model(col: Any, model: dict[str, Any]) -> dict[str, Any]:
    cloned = col.models.copy(model, add=False)
    cloned["name"] = unique_lookup_model_name(col, model["name"])
    ensure_lookup_field(col, cloned)
    apply_lookup_assets(cloned)
    col.models.add(cloned)
    return cloned


def refresh_lookup_model(col: Any, model: dict[str, Any]) -> None:
    base_model = find_base_model_for_lookup(col, model)
    if base_model:
        refreshed = col.models.copy(base_model, add=False)
        refreshed["id"] = model["id"]
        refreshed["name"] = model["name"]
        ensure_lookup_field(col, refreshed)
        if apply_lookup_assets(refreshed):
            col.models.update_dict(refreshed, skip_checks=True)
        return

    ensure_lookup_field(col, model)
    ensure_front_template(model)
    if apply_lookup_assets(model):
        col.models.update_dict(model, skip_checks=True)


def convert_notes_to_model(col: Any, note_ids: Sequence[int], old_model: dict[str, Any], new_model: dict[str, Any]) -> None:
    field_map = build_lookup_field_map(old_model, new_model)
    template_map = build_lookup_template_map(old_model, new_model)
    col.models.change(old_model, list(note_ids), new_model, field_map, template_map)


def convert_legacy_notes_to_model(col: Any, note_ids: Sequence[int], old_model: dict[str, Any], new_model: dict[str, Any]) -> None:
    field_map = build_legacy_field_map(old_model, new_model)
    template_map = build_legacy_template_map(old_model)
    col.models.change(old_model, list(note_ids), new_model, field_map, template_map)


def ensure_lookup_field(col: Any, model: dict[str, Any]) -> None:
    field_names = {field["name"] for field in model["flds"]}
    if LOOKUP_FIELD_NAME in field_names:
        return

    field = col.models.new_field(LOOKUP_FIELD_NAME)
    col.models.add_field(model, field)


def apply_lookup_assets(model: dict[str, Any]) -> bool:
    changed = False

    patched_css = patch_lookup_css(model.get("css", ""))
    if patched_css != model.get("css"):
        model["css"] = patched_css
        changed = True

    for template in model["tmpls"]:
        patched_afmt = patch_lookup_template(template.get("afmt", ""))
        if patched_afmt != template.get("afmt"):
            template["afmt"] = patched_afmt
            changed = True

    return changed

def patch_lookup_css(css: str) -> str:
    marker_start = "/* lapis-lookup-v1:start */"
    marker_end = "/* lapis-lookup-v1:end */"
    if marker_start in css and marker_end in css:
        start = css.index(marker_start)
        end = css.index(marker_end, start) + len(marker_end)
        css = f"{css[:start].rstrip()}\n\n{css[end:].lstrip()}"

    css = css.rstrip()
    return f"{css}\n\n{LOOKUP_CSS_BLOCK}\n" if css else f"{LOOKUP_CSS_BLOCK}\n"


def patch_lookup_template(afmt: str) -> str:
    markup_start = "<!-- lapis-lookup-v1:markup:start -->"
    markup_end = "<!-- lapis-lookup-v1:markup:end -->"

    if markup_start in afmt and markup_end in afmt:
        start = afmt.index(markup_start)
        end = afmt.index(markup_end, start) + len(markup_end)
        afmt = f"{afmt[:start].rstrip()}\n\n{afmt[end:].lstrip()}"

    afmt = re.sub(
        r'\s*<script>\s*\(\(\) => \{\s*if \(window\.__lapisLookupInitialized\) return;.*?</script>\s*$',
        "",
        afmt,
        count=1,
        flags=re.S,
    ).rstrip()

    image_modal_marker = "<!------- Image modal --------->"
    if image_modal_marker in afmt:
        afmt = afmt.replace(
            image_modal_marker,
            f"{LOOKUP_MARKUP_BLOCK}\n\n    {image_modal_marker}",
            1,
        )
    else:
        afmt = f"{afmt}\n\n{LOOKUP_MARKUP_BLOCK}"

    return f"{afmt.rstrip()}\n\n{LOOKUP_SCRIPT_BLOCK}\n"


def find_base_model_for_lookup(col: Any, model: dict[str, Any]) -> dict[str, Any] | None:
    model_name = model.get("name", "")
    match = re.fullmatch(r"(.+)\+Lookup(?: \d+)?", model_name)
    if not match:
        return None

    base_name = match.group(1)
    existing_models = col.models.all_names_and_ids()
    base_model_id = next(
        (item.id for item in existing_models if item.name == base_name),
        None,
    )
    if base_model_id is None:
        return None

    return copy.deepcopy(col.models.get(base_model_id))


def ensure_canonical_lookup_model(col: Any) -> dict[str, Any]:
    model = get_model_by_name(col, CANONICAL_LAPIS_MODEL_NAME)
    if model is None:
        model = create_canonical_lookup_model(col)
    else:
        if sync_canonical_lookup_model(col, model):
            col.models.update_dict(model, skip_checks=True)
    return model


def create_canonical_lookup_model(col: Any) -> dict[str, Any]:
    model = col.models.new(CANONICAL_LAPIS_MODEL_NAME)
    model["flds"] = []
    model["tmpls"] = []
    for field_spec in LAPIS_FIELDS:
        field = col.models.new_field(field_spec["name"])
        if "font" in field_spec:
            field["font"] = field_spec["font"]
        if "size" in field_spec:
            field["size"] = field_spec["size"]
        col.models.add_field(model, field)
    template = col.models.new_template("Mining")
    template["qfmt"] = FRONT_TEMPLATE
    template["afmt"] = BACK_TEMPLATE
    col.models.add_template(model, template)
    model["css"] = STYLING_CSS
    model["sortf"] = next(
        index for index, field in enumerate(model["flds"]) if field["name"] == "Expression"
    )
    col.models.add(model)
    return model


def sync_canonical_lookup_model(col: Any, model: dict[str, Any]) -> bool:
    changed = False
    expected_names = [field["name"] for field in LAPIS_FIELDS]
    existing_names = [field["name"] for field in model["flds"]]

    for field_spec in LAPIS_FIELDS:
        if field_spec["name"] in existing_names:
            continue
        field = col.models.new_field(field_spec["name"])
        if "font" in field_spec:
            field["font"] = field_spec["font"]
        if "size" in field_spec:
            field["size"] = field_spec["size"]
        col.models.add_field(model, field)
        changed = True

    field_lookup = {field["name"]: field for field in model["flds"]}
    reordered_fields = [field_lookup[name] for name in expected_names if name in field_lookup]
    if [field["name"] for field in reordered_fields] != existing_names:
        model["flds"] = reordered_fields
        changed = True

    if not model["tmpls"]:
        template = col.models.new_template("Mining")
        model["tmpls"] = [template]
        changed = True

    if len(model["tmpls"]) > 1:
        model["tmpls"] = [model["tmpls"][0]]
        changed = True

    template = model["tmpls"][0]
    if template.get("name") != "Mining":
        template["name"] = "Mining"
        changed = True

    if template.get("qfmt") != FRONT_TEMPLATE:
        template["qfmt"] = FRONT_TEMPLATE
        changed = True
    if template.get("afmt") != BACK_TEMPLATE:
        template["afmt"] = BACK_TEMPLATE
        changed = True
    if model.get("css") != STYLING_CSS:
        model["css"] = STYLING_CSS
        changed = True

    expression_index = next(
        index for index, field in enumerate(model["flds"]) if field["name"] == "Expression"
    )
    if int(model.get("sortf", -1)) != expression_index:
        model["sortf"] = expression_index
        changed = True

    return changed


def get_model_by_name(col: Any, name: str) -> dict[str, Any] | None:
    by_name = getattr(col.models, "by_name", None)
    if callable(by_name):
        return by_name(name)

    for item in col.models.all_names_and_ids():
        if item.name == name:
            return col.models.get(item.id)
    return None


def write_generated_fields(note: Any, generated_fields: dict[str, str]) -> None:
    for field_name, value in generated_fields.items():
        if field_name in note:
            note[field_name] = value


def run_lookup_cli(config: dict[str, Any], note_ids: Sequence[int], col: Any) -> dict[str, Any]:
    repo_root = Path(config["lookup_repo_root"]).expanduser()
    tool_root = repo_root / "tools" / "lookup"
    cli_path = tool_root / "dist" / "src" / "cli.js"
    fetch_path = tool_root / "dist" / "scripts" / "fetch-dictionaries.js"

    ensure_node_ready(tool_root, cli_path, fetch_path)

    payload = {
        "items": build_lookup_items(note_ids, col),
        "maxWordsPerKanji": int(config.get("max_words_per_kanji", 12)),
        "definitionDictionaryNames": config.get("definition_dictionary_names", ["Jitendex"]),
        "frequencyDictionaryNames": config.get("frequency_dictionary_names", ["JPDB"]),
    }

    node = resolve_executable("node")
    if not node:
        raise RuntimeError("node was not found on PATH.")

    completed = subprocess.run(
        [node, str(cli_path)],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=tool_root,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Lookup CLI failed.")

    return json.loads(completed.stdout)


def build_lookup_items(note_ids: Sequence[int], col: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for note_id in note_ids:
        note = col.get_note(note_id)
        model = note.note_type()
        if is_lapis_model(model):
            items.append(
                {
                    "noteId": note_id,
                    "mode": LOOKUP_ONLY_MODE,
                    "expression": note["Expression"],
                }
            )
            continue

        expression = extract_sort_field_expression(note)
        items.append(
            {
                "noteId": note_id,
                "mode": LEGACY_CONVERT_MODE,
                "expression": expression,
            }
        )
    return items


def ensure_node_ready(tool_root: Path, cli_path: Path, fetch_path: Path) -> None:
    node = resolve_executable("node")
    npm = resolve_executable("npm")
    if not node or not npm:
        raise RuntimeError("Both node and npm must be installed and available on PATH.")

    if not cli_path.exists():
        install_command = [npm, "ci"] if (tool_root / "package-lock.json").exists() else [npm, "install"]
        run_command(install_command, tool_root)
        run_command([npm, "run", "build"], tool_root)

    cache_dir = tool_root.parent.parent / ".cache" / "yomitan-dicts"
    required_archives = {
        "jitendex-yomitan.zip",
        "KANJIDIC_english.zip",
        "JPDB_v2.2_Frequency_Kana_2024-10-13.zip",
        "JPDB_Kanji.zip",
    }
    if not cache_dir.exists() or any(not (cache_dir / file_name).exists() for file_name in required_archives):
        if not fetch_path.exists():
            run_command([npm, "run", "build"], tool_root)
        run_command([node, str(fetch_path)], tool_root)


def run_command(command: Sequence[str], cwd: Path) -> None:
    env = os.environ.copy()
    env["npm_config_registry"] = "https://registry.npmjs.org/"
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Command failed: {' '.join(command)}")


def resolve_executable(name: str) -> str | None:
    direct = shutil.which(name)
    if direct:
        return direct

    env_name = f"LAPIS_{name.upper()}_PATH"
    configured = os.environ.get(env_name)
    if configured and Path(configured).exists():
        return configured

    home = Path.home()
    candidates = [
        home / ".nvm" / "versions" / "node",
        home / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]

    for base in candidates:
        candidate = base / name
        if candidate.exists():
            return str(candidate)

    if name in {"node", "npm"}:
        matches = sorted(
            glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "bin" / name)),
            reverse=True,
        )
        if matches:
            return matches[0]

    return None


def unique_lookup_model_name(col: Any, base_name: str) -> str:
    desired = f"{base_name}+Lookup"
    existing_names = {name.name for name in col.models.all_names_and_ids()}
    if desired not in existing_names:
        return desired

    suffix = 2
    while True:
        candidate = f"{desired} {suffix}"
        if candidate not in existing_names:
            return candidate
        suffix += 1


def load_config() -> dict[str, Any]:
    return mw.addonManager.getConfig(ADDON_NAME) or {}
