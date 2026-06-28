from __future__ import annotations

import glob
import base64
import copy
import html
import json
import os
import queue
import re
import shutil
import subprocess
import threading
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from anki import hooks as anki_hooks
from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu, QTimer, qconnect
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
from .lookup_store import (
    LOOKUP_STORE_MEDIA_NAME,
    LOOKUP_STORE_SHARD_PREFIX,
    LOOKUP_STORE_SHARD_SUFFIX,
    merge_lookup_terms,
    parse_lookup_store_envelope,
    read_lookup_store_from_media,
    write_lookup_store_to_media,
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
    is_lookup_ready_model,
    partition_note_ids,
)

ADDON_NAME = __name__.split(".")[0]


@dataclass
class BackfillSummary:
    processed: int
    converted: int
    skipped: int
    warnings: list[str]
    failed: int = 0
    failures: list[str] = field(default_factory=list)
    invariant_violations: list[str] = field(default_factory=list)
    affected_note_ids: set[int] = field(default_factory=set)


@dataclass
class BackfillState:
    canonical_model: dict[str, Any] | None = None
    affected_note_ids: set[int] = field(default_factory=set)


@dataclass
class AutoBackfillQueueState:
    pending_note_ids: list[int] = field(default_factory=list)
    running: bool = False


AUTO_BACKFILL_QUEUE = AutoBackfillQueueState()
PENDING_ADDED_NOTES: list[tuple[Any, int]] = []


def init() -> None:
    append_hook_once(gui_hooks.browser_menus_did_init, add_browser_menu)
    add_cards_did_add_note = getattr(gui_hooks, "add_cards_did_add_note", None)
    if add_cards_did_add_note is not None:
        append_hook_once(add_cards_did_add_note, on_add_cards_did_add_note)
    note_will_be_added = getattr(anki_hooks, "note_will_be_added", None)
    if note_will_be_added is not None:
        append_hook_once(note_will_be_added, on_note_will_be_added)


def append_hook_once(hook: Any, callback: Any) -> None:
    callbacks = getattr(hook, "_hooks", hook)
    try:
        already_registered = callback in callbacks
    except TypeError:
        already_registered = False
    if not already_registered:
        hook.append(callback)


def reset_auto_backfill_queue() -> None:
    AUTO_BACKFILL_QUEUE.pending_note_ids.clear()
    AUTO_BACKFILL_QUEUE.running = False
    PENDING_ADDED_NOTES.clear()


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

    export_action = QAction("Export Lookup Debug Bundle Selected Notes", browser)
    export_action.setMenuRole(QAction.MenuRole.NoRole)
    qconnect(export_action.triggered, lambda: export_lookup_debug_bundle_selected_notes(browser))
    menu.addAction(export_action)


def setup_and_backfill_selected_notes(browser: Browser) -> None:
    note_ids = list(browser.selected_notes())
    if not note_ids:
        showWarning("Select at least one note in Browse first.", parent=browser)
        return

    lookup_items = build_lookup_items(note_ids, mw.col)
    start_lookup_job(
        parent=browser,
        lookup_items=lookup_items,
        success=lambda results: on_backfill_success(
            browser,
            apply_backfill_results(mw.col, results),
        ),
        progress_label="Preparing Lapis lookup...",
    )


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
        template_ready = is_lookup_ready_model(model)
        payload_length = len(note[LOOKUP_FIELD_NAME]) if has_lookup_field else 0
        lines.extend(
            [
                f"Note ID: {note.id}",
                f"Notetype: {model['name']}",
                f"Lookup field exists: {'yes' if has_lookup_field else 'no'}",
                f"Lookup template active: {'yes' if template_marked else 'no'}",
                f"Lookup template ready: {'yes' if template_ready else 'no'}",
                f"Lookup payload length: {payload_length}",
                "",
            ]
        )

    showInfo("\n".join(lines).strip(), parent=browser)


def export_lookup_debug_bundle_selected_notes(browser: Browser) -> None:
    note_ids = list(browser.selected_notes())
    if not note_ids:
        showWarning("Select at least one note in Browse first.", parent=browser)
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path.home() / "Desktop" / f"lapis_lookup_debug_bundle_{timestamp}"
    bundle_path = export_lookup_debug_bundle(
        mw.col,
        note_ids,
        output_dir,
        config=load_config(),
    )
    showInfo(f"Exported Lapis lookup debug bundle:\n{bundle_path}", parent=browser)


def run_lookup_only(
    lookup_items: Sequence[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    return run_lookup_cli(config, lookup_items)


def apply_backfill_results(col: Any, results: dict[str, Any]) -> BackfillSummary:
    state = BackfillState()
    return apply_pending_lookup_items(col, results.get("results", []), state)


def on_backfill_success(browser: Browser, summary: BackfillSummary) -> None:
    browser.search()
    if summary.failed or summary.invariant_violations:
        showWarning(format_backfill_failure_report(summary), parent=browser)
        return

    message = format_backfill_success_line(summary)
    tooltip(message, parent=browser)
    if summary.warnings:
        showInfo("\n".join(summary.warnings[:50]), parent=browser)


def on_add_cards_did_add_note(note: Any) -> None:
    col = getattr(mw, "col", None)
    note_id = int(getattr(note, "id", 0) or 0)
    if col is None or note_id <= 0:
        return

    enqueue_auto_backfill_note_id(col, note_id)


def on_note_will_be_added(col: Any, note: Any, _deck_id: Any) -> None:
    if not is_auto_backfill_note_eligible(note):
        return
    PENDING_ADDED_NOTES.append((note, 5))
    schedule_pending_added_note_drain()


def schedule_pending_added_note_drain(delay_ms: int = 0) -> None:
    try:
        QTimer.singleShot(delay_ms, drain_pending_added_notes)
    except Exception:
        drain_pending_added_notes()


def drain_pending_added_notes() -> None:
    if not PENDING_ADDED_NOTES:
        return

    remaining: list[tuple[Any, int]] = []
    col = getattr(mw, "col", None)
    for note, attempts_left in PENDING_ADDED_NOTES:
        note_id = int(getattr(note, "id", 0) or 0)
        if col is not None and note_id > 0:
            enqueue_auto_backfill_note_id(col, note_id)
            continue
        if attempts_left > 1:
            remaining.append((note, attempts_left - 1))

    PENDING_ADDED_NOTES[:] = remaining
    if PENDING_ADDED_NOTES:
        schedule_pending_added_note_drain(50)


def enqueue_auto_backfill_note_id(col: Any, note_id: int) -> None:
    if not is_auto_backfill_note_id_eligible(col, note_id):
        return
    if note_id not in AUTO_BACKFILL_QUEUE.pending_note_ids:
        AUTO_BACKFILL_QUEUE.pending_note_ids.append(note_id)
    start_auto_backfill_if_idle(col)


def is_auto_backfill_note_id_eligible(col: Any, note_id: int) -> bool:
    try:
        note = col.get_note(note_id)
    except Exception:
        return False
    return is_auto_backfill_note_eligible(note)


def is_auto_backfill_note_eligible(note: Any) -> bool:
    model = note.note_type()
    if not is_lapis_model(model):
        return False
    if not note_expression(note).strip():
        return False
    return not note_lookup_payload_text(note).strip()


def start_auto_backfill_if_idle(col: Any | None = None) -> None:
    if AUTO_BACKFILL_QUEUE.running:
        return

    col = col or getattr(mw, "col", None)
    if col is None:
        return

    note_ids = collect_pending_auto_backfill_note_ids(col)
    if not note_ids:
        return

    lookup_items = build_lookup_items(note_ids, col)
    if not lookup_items:
        start_auto_backfill_next_batch()
        return

    AUTO_BACKFILL_QUEUE.running = True
    try:
        start_lookup_job(
            parent=mw,
            lookup_items=lookup_items,
            success=on_auto_backfill_lookup_success,
            failure=on_auto_backfill_lookup_failure,
            progress_label="Preparing Lapis lookup...",
        )
    except Exception:
        AUTO_BACKFILL_QUEUE.pending_note_ids = note_ids + AUTO_BACKFILL_QUEUE.pending_note_ids
        AUTO_BACKFILL_QUEUE.running = False
        raise


def collect_pending_auto_backfill_note_ids(col: Any) -> list[int]:
    note_ids: list[int] = []
    for note_id in AUTO_BACKFILL_QUEUE.pending_note_ids:
        if is_auto_backfill_note_id_eligible(col, note_id):
            note_ids.append(note_id)
    AUTO_BACKFILL_QUEUE.pending_note_ids.clear()
    return note_ids


def on_auto_backfill_lookup_success(results: dict[str, Any]) -> None:
    try:
        summary = apply_backfill_results(mw.col, results)
    except Exception as error:
        showWarning(f"Lapis lookup auto-backfill failed.\n{error}", parent=mw)
    else:
        if summary.failed or summary.invariant_violations:
            showWarning(format_backfill_failure_report(summary), parent=mw)
    finally:
        start_auto_backfill_next_batch()


def on_auto_backfill_lookup_failure(error: Exception) -> None:
    showWarning(f"Lapis lookup auto-backfill failed.\n{error}", parent=mw)
    start_auto_backfill_next_batch()


def start_auto_backfill_next_batch() -> None:
    AUTO_BACKFILL_QUEUE.running = False
    start_auto_backfill_if_idle()


def start_lookup_job(
    *,
    parent: Any,
    lookup_items: Sequence[dict[str, Any]],
    success: Any,
    progress_label: str,
    failure: Any | None = None,
) -> None:
    if not lookup_items:
        return
    config = load_config()
    op = QueryOp(
        parent=parent,
        op=lambda _col: run_lookup_only(lookup_items, config),
        success=success,
    )
    if failure is not None:
        op = op.failure(failure)
    op.with_progress(progress_label).run_in_background()


def apply_backfill_item(col: Any, item: dict[str, Any], state: BackfillState) -> BackfillSummary:
    warnings: list[str] = list(item.get("warnings", []))
    note_id = item["noteId"]
    mode = item.get("mode", LOOKUP_ONLY_MODE)
    status = item.get("status", "ok")

    if status != "ok":
        return backfill_failure(note_id, item, warnings, f"lookup status was {status!r}")

    serialized_payload, payload_error = serialize_lookup_payload(item)
    if payload_error:
        return backfill_failure(note_id, item, warnings, payload_error)

    converted = 0

    def apply_item() -> None:
        nonlocal converted
        note = col.get_note(note_id)
        if mode == LEGACY_CONVERT_MODE:
            if state.canonical_model is None:
                state.canonical_model = ensure_canonical_lookup_model(col)
            convert_legacy_notes_to_model(
                col,
                [note_id],
                note.note_type(),
                state.canonical_model,
            )
            note = col.get_note(note_id)
            write_generated_fields(note, item.get("generatedFields", {}))
            converted = 1
        else:
            model = note.note_type()
            if not is_canonical_lookup_note(note):
                ensure_lookup_model_for_notes(col, [note_id], state=state)
                note = col.get_note(note_id)

        if not note_has_field(note, LOOKUP_FIELD_NAME):
            model = note.note_type()
            field_names = [field["name"] for field in model["flds"]]
            raise RuntimeError(
                "\n".join(
                    [
                        "lookup field unavailable after setup",
                        f"mode={mode}",
                        f"model={model.get('name', '<unknown>')}",
                        f"fields={field_names}",
                    ]
                )
            )

        note[LOOKUP_FIELD_NAME] = html.escape(serialized_payload, quote=False)
        col.update_note(note, skip_undo_entry=True)
        persisted_note = col.get_note(note_id)
        if not note_lookup_payload_text(persisted_note).strip():
            raise RuntimeError("lookup payload was blank after write")

    try:
        run_collection_transaction(col, f"Lapis lookup backfill note {note_id}", apply_item)
    except Exception as error:
        return backfill_failure(note_id, item, warnings, str(error))

    state.affected_note_ids.add(note_id)
    return BackfillSummary(
        processed=1,
        converted=converted,
        skipped=0,
        warnings=warnings,
        affected_note_ids={note_id},
    )


def serialize_lookup_payload(item: dict[str, Any]) -> tuple[str, str | None]:
    if "payload" not in item:
        return "", "lookup payload missing"
    if not isinstance(item["payload"], dict):
        return "", f"lookup payload had unexpected type {type(item['payload']).__name__}"
    try:
        serialized = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        return "", f"lookup payload could not be serialized: {error}"
    if not serialized.strip():
        return "", "lookup payload serialized to blank text"
    return serialized, None


def backfill_failure(
    note_id: int,
    item: dict[str, Any],
    warnings: list[str],
    reason: str,
) -> BackfillSummary:
    expression = str(item.get("expression", "")).strip()
    return BackfillSummary(
        processed=0,
        converted=0,
        skipped=1,
        warnings=warnings,
        failed=1,
        failures=[format_note_failure(note_id, expression, reason)],
    )


def run_collection_transaction(col: Any, description: str, op: Any) -> Any:
    transact = getattr(col, "transact", None)
    if callable(transact):
        try:
            return transact(op)
        except TypeError:
            return transact(description, op)
    return op()


def note_lookup_payload_text(note: Any) -> str:
    if not note_has_field(note, LOOKUP_FIELD_NAME):
        return ""
    try:
        return str(note[LOOKUP_FIELD_NAME])
    except (KeyError, IndexError, TypeError):
        return ""


def format_note_failure(note_id: int, expression: str, reason: str) -> str:
    label = f" ({expression})" if expression else ""
    return f"Note {note_id}{label}: {reason}"


def ensure_lookup_model_for_notes(
    col: Any,
    note_ids: Sequence[int],
    *,
    state: BackfillState | None = None,
) -> None:
    target_model = ensure_canonical_lookup_model_for_state(col, state)
    for model_id, model_note_ids in partition_note_ids(col, note_ids).items():
        model = col.models.get(model_id)
        if not is_lapis_model(model):
            continue
        if int(model["id"]) == int(target_model["id"]) and is_lookup_ready_model(model):
            continue
        convert_notes_to_model(col, model_note_ids, model, target_model)


def ensure_canonical_lookup_model_for_state(
    col: Any,
    state: BackfillState | None = None,
) -> dict[str, Any]:
    if state is not None and state.canonical_model is not None:
        return state.canonical_model

    model = ensure_canonical_lookup_model(col)
    if state is not None:
        state.canonical_model = model
    return model


def is_canonical_lookup_note(note: Any) -> bool:
    model = note.note_type()
    return is_canonical_lookup_model_ready(model) and note_has_field(note, LOOKUP_FIELD_NAME)


def is_canonical_lookup_model_ready(model: dict[str, Any]) -> bool:
    if model.get("name") != CANONICAL_LAPIS_MODEL_NAME or not is_lookup_ready_model(model):
        return False
    field_names = {field["name"] for field in model["flds"]}
    expected_field_names = {field["name"] for field in LAPIS_FIELDS}
    if not expected_field_names.issubset(field_names):
        return False
    if len(model.get("tmpls", [])) != 1:
        return False
    template = model["tmpls"][0]
    if template.get("name") != "Mining":
        return False
    if template.get("qfmt") != FRONT_TEMPLATE or template.get("afmt") != BACK_TEMPLATE:
        return False
    if model.get("css") != STYLING_CSS:
        return False
    expression_index = next(
        (index for index, field in enumerate(model["flds"]) if field["name"] == "Expression"),
        None,
    )
    return expression_index is not None and int(model.get("sortf", -1)) == expression_index


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


def note_has_field(note: Any, field_name: str) -> bool:
    model = note.note_type()
    return any(field["name"] == field_name for field in model["flds"])


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


def ensure_canonical_lookup_model(col: Any) -> dict[str, Any]:
    model = get_model_by_name(col, CANONICAL_LAPIS_MODEL_NAME)
    if model is None:
        model = create_canonical_lookup_model(col)
    else:
        if sync_canonical_lookup_model(col, model):
            col.models.update_dict(model, skip_checks=True)
            model = col.models.get(model["id"])
    if not is_canonical_lookup_model_ready(model):
        raise RuntimeError(
            f"canonical lookup model {CANONICAL_LAPIS_MODEL_NAME} is not ready after sync"
        )
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
        existing_names.append(field_spec["name"])
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
        if note_has_field(note, field_name):
            note[field_name] = value


def run_lookup_cli(
    config: dict[str, Any],
    lookup_items: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    repo_root = Path(config["lookup_repo_root"]).expanduser()
    tool_root = repo_root / "tools" / "lookup"
    cli_path = tool_root / "dist" / "src" / "cli.js"
    fetch_path = tool_root / "dist" / "scripts" / "fetch-dictionaries.js"

    ensure_node_ready(tool_root, cli_path, fetch_path)

    node = resolve_executable("node")
    if not node:
        raise RuntimeError("node was not found on PATH.")

    options = {
        "maxWordsPerKanji": int(config.get("max_words_per_kanji", 12)),
        "definitionDictionaryNames": config.get("definition_dictionary_names", ["Jitendex"]),
        "frequencyDictionaryNames": config.get("frequency_dictionary_names", ["JPDB"]),
        "streamResults": True,
    }
    chunk_size = max(1, int(config.get("lookup_chunk_size", 100)))
    note_timeout_seconds = max(1, int(config.get("note_timeout_seconds", 90)))

    update_lookup_progress(0, len(lookup_items), "Starting Lapis lookup...")

    results: list[dict[str, Any]] = []
    completed_count = 0
    index = 0

    while index < len(lookup_items):
        chunk_items = lookup_items[index : index + chunk_size]
        chunk_result = run_lookup_chunk(
            node=node,
            cli_path=cli_path,
            tool_root=tool_root,
            payload={**options, "items": chunk_items},
            config=config,
            total_count=len(lookup_items),
            completed_count=completed_count,
            timeout_seconds=note_timeout_seconds,
        )
        results.extend(chunk_result.items)
        completed_count += chunk_result.completed
        index += chunk_result.completed

    update_lookup_progress(completed_count, len(lookup_items), "Finishing Lapis lookup...")
    return {"results": results}


@dataclass
class ChunkResult:
    items: list[dict[str, Any]]
    completed: int


def run_lookup_chunk(
    *,
    node: str,
    cli_path: Path,
    tool_root: Path,
    payload: dict[str, Any],
    config: dict[str, Any],
    total_count: int,
    completed_count: int,
    timeout_seconds: int,
) -> ChunkResult:
    node_command = build_node_command(node, config, cli_path)
    process = subprocess.Popen(
        node_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tool_root,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_lines: list[str] = []
    stderr_thread = threading.Thread(
        target=drain_process_stderr,
        args=(process.stderr, stderr_lines),
        daemon=True,
    )
    stderr_thread.start()
    output_queue: queue.Queue[str | None] = queue.Queue()
    stdout_thread = threading.Thread(
        target=drain_process_stdout,
        args=(process.stdout, output_queue),
        daemon=True,
    )
    stdout_thread.start()
    process.stdin.write(json.dumps(payload, ensure_ascii=False))
    process.stdin.close()

    chunk_completed = 0
    result_items: list[dict[str, Any]] = []

    while True:
        try:
            line = output_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            process.kill()
            process.wait(timeout=5)
            stderr_thread.join(timeout=1)
            stdout_thread.join(timeout=1)
            skipped_item = payload["items"][chunk_completed]
            result_items.append(
                {
                    "noteId": skipped_item["noteId"],
                    "mode": skipped_item.get("mode", LOOKUP_ONLY_MODE),
                    "status": "skipped",
                    "expression": skipped_item.get("expression", ""),
                    "warnings": [
                        f"Skipped note {skipped_item['noteId']}: lookup for \"{skipped_item['expression']}\" exceeded {timeout_seconds} seconds."
                    ],
                }
            )
            update_lookup_progress(
                completed_count + chunk_completed + 1,
                total_count,
                f"Skipped timed-out note {completed_count + chunk_completed + 1} of {total_count}",
            )
            return ChunkResult(items=result_items, completed=chunk_completed + 1)

        if line is None:
            break
        stripped_line = line.strip()
        if not stripped_line:
            continue
        try:
            item = parse_lookup_stream_item(stripped_line)
        except (json.JSONDecodeError, ValueError) as error:
            process.kill()
            process.wait(timeout=5)
            raise RuntimeError(f"Lookup CLI returned invalid progress output: {stripped_line[:500]}") from error

        if item.get("type") == "progress":
            update_lookup_progress(
                completed_count + int(item.get("completed", chunk_completed)),
                total_count,
                format_lookup_progress_label(item, total_count, completed_count),
            )
            continue

        result_items.append(item)
        chunk_completed += 1
        update_lookup_progress(completed_count + chunk_completed, total_count, f"Prepared {completed_count + chunk_completed} of {total_count} notes...")

    return_code = process.wait()
    stderr_thread.join(timeout=1)
    stdout_thread.join(timeout=1)
    if return_code != 0:
        stderr = "".join(stderr_lines)
        raise RuntimeError(stderr.strip() or "Lookup CLI failed.")
    if chunk_completed != len(payload["items"]):
        raise RuntimeError(
            f"Lookup CLI exited before completing chunk: {chunk_completed} of {len(payload['items'])} note(s)."
        )

    return ChunkResult(items=result_items, completed=chunk_completed)


def apply_pending_lookup_items(
    col: Any,
    items: Sequence[dict[str, Any]],
    state: BackfillState,
) -> BackfillSummary:
    shared_terms: dict[str, Any] = {}
    for item in items:
        item_shared_terms = item.get("sharedTerms")
        if isinstance(item_shared_terms, dict):
            shared_terms.update(item_shared_terms)

    summary = BackfillSummary(processed=0, converted=0, skipped=0, warnings=[])
    if shared_terms:
        store = merge_lookup_terms(read_lookup_store_from_media(col), shared_terms)
        summary.warnings.extend(write_lookup_store_to_media(col, store))

    for item in items:
        item_summary = apply_backfill_item(col, item, state)
        summary.processed += item_summary.processed
        summary.converted += item_summary.converted
        summary.skipped += item_summary.skipped
        summary.failed += item_summary.failed
        summary.warnings.extend(item_summary.warnings)
        summary.failures.extend(item_summary.failures)
        summary.affected_note_ids.update(item_summary.affected_note_ids)

    summary.invariant_violations.extend(
        find_lookup_payload_violations(col, summary.affected_note_ids)
    )
    summary.failed += len(summary.invariant_violations)
    return summary


def find_lookup_payload_violations(col: Any, note_ids: set[int]) -> list[str]:
    violations: list[str] = []
    for note_id in sorted(note_ids):
        note = col.get_note(note_id)
        model = note.note_type()
        if not is_lookup_enabled_model(model):
            continue
        if not note_has_field(note, LOOKUP_FIELD_NAME) or not note_lookup_payload_text(note).strip():
            violations.append(
                format_note_failure(
                    note_id,
                    note_expression(note),
                    "lookup-enabled note has blank KanjiLookupData",
                )
            )
    return violations


def note_expression(note: Any) -> str:
    if note_has_field(note, "Expression"):
        try:
            return str(note["Expression"])
        except (KeyError, IndexError, TypeError):
            return ""
    try:
        return extract_sort_field_expression(note)
    except Exception:
        return ""


def format_backfill_success_line(summary: BackfillSummary) -> str:
    message = f"Processed {summary.processed} note(s)"
    if summary.converted:
        message += f", converted {summary.converted}"
    if summary.skipped:
        message += f", skipped {summary.skipped}"
    return message


def format_backfill_failure_report(summary: BackfillSummary) -> str:
    lines = [
        "Lapis lookup backfill finished with failures.",
        f"Processed: {summary.processed}",
        f"Converted: {summary.converted}",
        f"Skipped: {summary.skipped}",
        f"Failed: {summary.failed}",
    ]
    if summary.failures:
        lines.extend(["", "Failures:"])
        lines.extend(truncate_report_lines(summary.failures, 50))
    if summary.invariant_violations:
        lines.extend(["", "Processed notes left blank:"])
        lines.extend(truncate_report_lines(summary.invariant_violations, 50))
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(truncate_report_lines(summary.warnings, 50))
    return "\n".join(lines)


def truncate_report_lines(values: Sequence[str], limit: int) -> list[str]:
    lines = list(values[:limit])
    if len(values) > limit:
        lines.append(f"... {len(values) - limit} more")
    return lines


def build_node_command(node: str, config: dict[str, Any], cli_path: Path) -> list[str]:
    command = [node]
    max_old_space_mb = config.get("node_max_old_space_mb")
    if max_old_space_mb:
        command.append(f"--max-old-space-size={int(max_old_space_mb)}")
    command.append(str(cli_path))
    return command


def drain_process_stdout(stdout: Any, output_queue: queue.Queue[str | None]) -> None:
    for line in stdout:
        output_queue.put(line)
    output_queue.put(None)


def drain_process_stderr(stderr: Any, stderr_lines: list[str]) -> None:
    for line in stderr:
        stderr_lines.append(line)


def parse_lookup_stream_item(line: str) -> dict[str, Any]:
    if line.startswith("{"):
        return json.loads(line)

    decoded = base64.b64decode(line, validate=True).decode("utf-8")
    return json.loads(decoded)


def format_lookup_progress_label(item: dict[str, Any], total: int, completed_offset: int = 0) -> str:
    completed = int(item.get("completed", 0))
    current = completed_offset + completed + 1
    expression = str(item.get("expression", "")).strip()
    if len(expression) > 32:
        expression = f"{expression[:29]}..."
    suffix = f": {expression}" if expression else ""
    return f"Looking up note {current} of {total}{suffix}"


def update_lookup_progress(value: int, maximum: int, label: str) -> None:
    taskman = getattr(mw, "taskman", None)
    if taskman is None:
        return

    taskman.run_on_main(
        lambda: mw.progress.update(label=label, value=value, max=maximum)
    )


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
        run_command(install_command, tool_root, node_path=node, npm_path=npm)
        run_command([npm, "run", "build"], tool_root, node_path=node, npm_path=npm)
    elif needs_tool_rebuild(tool_root, cli_path, fetch_path):
        run_command([npm, "run", "build"], tool_root, node_path=node, npm_path=npm)

    cache_dir = tool_root.parent.parent / ".cache" / "yomitan-dicts"
    required_archives = {
        "jitendex-yomitan.zip",
        "KANJIDIC_english.zip",
        "JPDB_v2.2_Frequency_Kana_2024-10-13.zip",
        "JPDB_Kanji.zip",
    }
    if not cache_dir.exists() or any(not (cache_dir / file_name).exists() for file_name in required_archives):
        if not fetch_path.exists():
            run_command([npm, "run", "build"], tool_root, node_path=node, npm_path=npm)
        run_command([node, str(fetch_path)], tool_root, node_path=node, npm_path=npm)


def needs_tool_rebuild(tool_root: Path, cli_path: Path, fetch_path: Path) -> bool:
    outputs = [path for path in (cli_path, fetch_path) if path.exists()]
    if len(outputs) < 2:
        return True

    oldest_output_mtime = min(path.stat().st_mtime for path in outputs)
    source_roots = [
        tool_root / "src",
        tool_root / "scripts",
    ]
    source_files = [
        tool_root / "package.json",
        tool_root / "package-lock.json",
        tool_root / "tsconfig.json",
    ]

    for root in source_roots:
        if root.exists():
            source_files.extend(path for path in root.rglob("*.ts") if path.is_file())

    for path in source_files:
        if path.exists() and path.stat().st_mtime > oldest_output_mtime:
            return True

    return False


def run_command(
    command: Sequence[str],
    cwd: Path,
    *,
    node_path: str | None = None,
    npm_path: str | None = None,
) -> None:
    env = os.environ.copy()
    env["npm_config_registry"] = "https://registry.npmjs.org/"
    env["PATH"] = build_command_path(env.get("PATH", ""), node_path, npm_path)
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Command failed: {' '.join(command)}")


def build_command_path(existing_path: str, node_path: str | None, npm_path: str | None) -> str:
    path_parts: list[str] = []
    for executable_path in (node_path, npm_path):
        if executable_path:
            parent = str(Path(executable_path).resolve().parent)
            if parent not in path_parts:
                path_parts.append(parent)
    if existing_path:
        path_parts.append(existing_path)
    return os.pathsep.join(path_parts)


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


def load_config() -> dict[str, Any]:
    return mw.addonManager.getConfig(ADDON_NAME) or {}


def export_lookup_debug_bundle(
    col: Any,
    note_ids: Sequence[int],
    output_dir: Path,
    *,
    config: dict[str, Any] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_dir = output_dir / "notes"
    notes_dir.mkdir(exist_ok=True)

    bundle_notes: list[dict[str, Any]] = []
    models_by_id: dict[int, dict[str, Any]] = {}
    for note_id in note_ids:
        note = col.get_note(note_id)
        model = copy.deepcopy(note.note_type())
        model_id = int(model["id"])
        models_by_id[model_id] = model
        field_names = [field["name"] for field in model["flds"]]
        fields = note_field_map(note)
        raw_fields = raw_note_fields_text(col, note_id)
        replay_html = render_replay_back_html(model, fields)
        replay_name = f"note_{note_id}.html"
        (notes_dir / replay_name).write_text(replay_html, encoding="utf-8")
        bundle_notes.append(
            {
                "id": note_id,
                "mid": getattr(note, "mid", model_id),
                "modelName": model.get("name", ""),
                "fieldNames": field_names,
                "fields": fields,
                "rawFields": raw_fields,
                "expression": fields.get("Expression", note_expression(note)),
                "kanjiLookupData": fields.get(LOOKUP_FIELD_NAME, ""),
                "replayHtml": f"notes/{replay_name}",
            }
        )

    media_manifest = copy_lookup_store_media(col, output_dir)
    bundle = {
        "version": 1,
        "exportedAt": datetime.now().isoformat(timespec="seconds"),
        "addon": ADDON_NAME,
        "config": config or {},
        "notes": bundle_notes,
        "models": list(models_by_id.values()),
        "assets": {
            "frontTemplate": FRONT_TEMPLATE,
            "backTemplate": BACK_TEMPLATE,
            "stylingCss": STYLING_CSS,
            "lookupCssBlock": LOOKUP_CSS_BLOCK,
            "lookupMarkupBlock": LOOKUP_MARKUP_BLOCK,
            "lookupScriptBlock": LOOKUP_SCRIPT_BLOCK,
        },
        "media": media_manifest,
    }
    (output_dir / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_dir


def note_field_map(note: Any) -> dict[str, str]:
    model = note.note_type()
    values: dict[str, str] = {}
    fields = list(getattr(note, "fields", []))
    for index, field in enumerate(model["flds"]):
        name = field["name"]
        if index < len(fields):
            values[name] = str(fields[index])
            continue
        try:
            values[name] = str(note[name])
        except (KeyError, IndexError, TypeError):
            values[name] = ""
    return values


def raw_note_fields_text(col: Any, note_id: int) -> str | None:
    db = getattr(col, "db", None)
    scalar = getattr(db, "scalar", None)
    if callable(scalar):
        try:
            return scalar("select flds from notes where id = ?", note_id)
        except TypeError:
            return scalar("select flds from notes where id = ?", int(note_id))
    note = col.get_note(note_id)
    fields = getattr(note, "fields", None)
    if fields is None:
        return None
    return "\x1f".join(str(field) for field in fields)


def render_replay_back_html(model: dict[str, Any], fields: dict[str, str]) -> str:
    template = model["tmpls"][0].get("afmt", BACK_TEMPLATE) if model.get("tmpls") else BACK_TEMPLATE
    body = render_anki_template(template, fields)
    css = model.get("css", STYLING_CSS)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="ja">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<base href="../">',
            f"<style>{css}</style>",
            "</head>",
            "<body>",
            body,
            "</body>",
            "</html>",
        ]
    )


def render_anki_template(template: str, fields: dict[str, str]) -> str:
    rendered = template
    for name, value in fields.items():
        rendered = render_anki_sections(rendered, name, value)
    rendered = re.sub(r"{{[#^][^}]+}}.*?{{/[^}]+}}", "", rendered, flags=re.S)
    rendered = re.sub(
        r"{{(?:text:|furigana:|kana:|kanji:)?([^}]+)}}",
        lambda match: fields.get(match.group(1).strip(), ""),
        rendered,
    )
    return rendered


def render_anki_sections(template: str, field_name: str, value: str) -> str:
    escaped_name = re.escape(field_name)
    truthy_pattern = re.compile(r"{{#" + escaped_name + r"}}(.*?){{/" + escaped_name + r"}}", re.S)
    falsey_pattern = re.compile(r"{{\^" + escaped_name + r"}}(.*?){{/" + escaped_name + r"}}", re.S)
    template = truthy_pattern.sub(lambda match: match.group(1) if value else "", template)
    return falsey_pattern.sub(lambda match: "" if value else match.group(1), template)


def copy_lookup_store_media(col: Any, output_dir: Path) -> dict[str, Any]:
    media_dir = collection_media_dir(col)
    copied: list[str] = []
    missing: list[str] = []
    expected = [LOOKUP_STORE_MEDIA_NAME]
    if media_dir is None:
        return {"mediaDir": None, "expected": expected, "copied": copied, "missing": expected}

    manifest_path = media_dir / LOOKUP_STORE_MEDIA_NAME
    if not manifest_path.exists():
        return {"mediaDir": str(media_dir), "expected": expected, "copied": copied, "missing": expected}

    shutil.copy2(manifest_path, output_dir / LOOKUP_STORE_MEDIA_NAME)
    copied.append(LOOKUP_STORE_MEDIA_NAME)
    try:
        envelope = parse_lookup_store_envelope(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception:
        envelope = {}
    shard_count = int(envelope.get("shardCount", 64))
    shard_prefix = str(envelope.get("shardPrefix", LOOKUP_STORE_SHARD_PREFIX))
    shard_suffix = str(envelope.get("shardSuffix", LOOKUP_STORE_SHARD_SUFFIX))
    for shard_index in range(shard_count):
        shard_name = f"{shard_prefix}{shard_index:02d}{shard_suffix}"
        expected.append(shard_name)
        shard_path = media_dir / shard_name
        if shard_path.exists():
            shutil.copy2(shard_path, output_dir / shard_name)
            copied.append(shard_name)
        else:
            missing.append(shard_name)
    return {"mediaDir": str(media_dir), "expected": expected, "copied": copied, "missing": missing}


def collection_media_dir(col: Any) -> Path | None:
    media = getattr(col, "media", None)
    media_dir = getattr(media, "dir", None)
    if not callable(media_dir):
        return None
    return Path(media_dir())
