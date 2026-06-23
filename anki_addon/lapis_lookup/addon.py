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
    LOOKUP_CSS_BLOCK,
    LOOKUP_MARKUP_BLOCK,
    LOOKUP_SCRIPT_BLOCK,
)

LOOKUP_FIELD_NAME = "KanjiLookupData"
LOOKUP_TEMPLATE_MARKER = "lapis-lookup-v1"
ADDON_NAME = __name__.split(".")[0]
CORE_LAPIS_FIELDS = {
    "Expression",
    "ExpressionFurigana",
    "MainDefinition",
    "Glossary",
    "Sentence",
    "FreqSort",
}


@dataclass
class BackfillSummary:
    processed: int
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

    try:
        model = mw.col.models.get(mw.col.models.get_single_notetype_of_notes(note_ids))
    except Exception as error:
        showWarning(str(error), parent=browser)
        return

    if not is_lapis_model(model):
        showWarning("This command currently supports Lapis-family note types only.", parent=browser)
        return

    config = load_config()

    try:
        ensure_lookup_model_for_notes(mw.col, note_ids)
    except Exception as error:
        showWarning(str(error), parent=browser)
        return

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
    model_id = col.models.get_single_notetype_of_notes(note_ids)
    model = col.models.get(model_id)
    if not is_lapis_model(model):
        raise ValueError("Selected notes are not on a supported Lapis-family note type.")

    results = run_lookup_cli(config, note_ids, col)
    warnings: list[str] = []
    processed = 0
    skipped = 0

    for item in results.get("results", []):
        note_id = item["noteId"]
        note = col.get_note(note_id)
        if LOOKUP_FIELD_NAME not in note:
            skipped += 1
            warnings.append(f"Skipped note {note_id}: {LOOKUP_FIELD_NAME} missing after conversion.")
            continue

        serialized_payload = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
        note[LOOKUP_FIELD_NAME] = html.escape(serialized_payload, quote=False)
        col.update_note(note, skip_undo_entry=True)
        processed += 1
        warnings.extend(item.get("warnings", []))

    return BackfillSummary(processed=processed, skipped=skipped, warnings=warnings)


def on_backfill_success(browser: Browser, summary: BackfillSummary) -> None:
    browser.search()
    message = f"Processed {summary.processed} note(s)"
    if summary.skipped:
        message += f", skipped {summary.skipped}"
    tooltip(message, parent=browser)

    if summary.warnings:
        showInfo("\n".join(summary.warnings[:50]), parent=browser)


def ensure_lookup_model_for_notes(col: Any, note_ids: Sequence[int]) -> None:
    model_id = col.models.get_single_notetype_of_notes(note_ids)
    model = col.models.get(model_id)
    if is_lookup_enabled_model(model):
        refresh_lookup_model(col, model)
        return

    target_model = clone_lookup_model(col, model)
    convert_notes_to_model(col, note_ids, model, target_model)


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
    if apply_lookup_assets(model):
        col.models.update_dict(model, skip_checks=True)


def convert_notes_to_model(col: Any, note_ids: Sequence[int], old_model: dict[str, Any], new_model: dict[str, Any]) -> None:
    field_map = {index: index for index in range(len(old_model["flds"]))}
    field_map[len(new_model["flds"]) - 1] = None
    template_map = {index: index for index in range(len(old_model["tmpls"]))}
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


def run_lookup_cli(config: dict[str, Any], note_ids: Sequence[int], col: Any) -> dict[str, Any]:
    repo_root = Path(config["lookup_repo_root"]).expanduser()
    tool_root = repo_root / "tools" / "lookup"
    cli_path = tool_root / "dist" / "src" / "cli.js"
    fetch_path = tool_root / "dist" / "scripts" / "fetch-dictionaries.js"

    ensure_node_ready(tool_root, cli_path, fetch_path)

    payload = {
        "items": [{"noteId": note_id, "expression": col.get_note(note_id)["Expression"]} for note_id in note_ids],
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


def is_lapis_model(model: dict[str, Any]) -> bool:
    field_names = {field["name"] for field in model["flds"]}
    return CORE_LAPIS_FIELDS.issubset(field_names)


def is_lookup_enabled_model(model: dict[str, Any]) -> bool:
    field_names = {field["name"] for field in model["flds"]}
    if LOOKUP_FIELD_NAME not in field_names:
        return False
    return any(LOOKUP_TEMPLATE_MARKER in template["afmt"] for template in model["tmpls"])


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
