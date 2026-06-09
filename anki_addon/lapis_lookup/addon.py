from __future__ import annotations

import html
import json
import os
import glob
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu, qconnect
from aqt.utils import showInfo, showWarning, tooltip

LOOKUP_FIELD_NAME = "KanjiLookupData"
LOOKUP_TEMPLATE_MARKER = "lapis-lookup-v1"
ADDON_NAME = __name__.split(".")[0]
LOOKUP_DEBUG_LOG_PATH = Path(__file__).with_name("lapis_lookup_debug.log")
LOOKUP_DEBUG_PREVIEW_LIMIT = 320
CORE_LAPIS_FIELDS = {
    "Expression",
    "ExpressionFurigana",
    "MainDefinition",
    "Glossary",
    "Sentence",
    "FreqSort",
}

LOOKUP_CSS_BLOCK = """
/* lapis-lookup-v1 */
.hidden {
  display: none !important;
}

.lapis-lookup-kanji-target {
  appearance: none;
  border: 0;
  padding: 0;
  margin: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  border-bottom: 0.08em solid var(--bold);
}

.lapis-lookup-overlay {
  position: absolute;
  inset: 0;
  z-index: 1500;
  background: var(--bg-color);
  padding: 18px;
  overflow-y: auto;
}

.lapis-lookup-sheet {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
}

.lapis-lookup-sheet-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.lapis-lookup-back {
  appearance: none;
  border: 1px solid var(--fg-subtle);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--fg-color);
  font-family: var(--font-sans);
  font-size: 0.9em;
  padding: 6px 12px;
}

.lapis-lookup-sheet-title-wrap {
  flex: 1;
  min-width: 0;
  text-align: left;
}

.lapis-lookup-sheet-title {
  font-family: var(--font-serif);
  font-size: calc(var(--back-vocab-font-size) * 0.8);
  line-height: 1.05;
}

.lapis-lookup-sheet-subtitle {
  color: var(--fg-subtle);
  font-family: var(--font-sans);
  font-size: 0.9em;
  margin-top: 4px;
}

.lapis-lookup-sheet-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.lapis-lookup-word-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.lapis-lookup-word-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  box-sizing: border-box;
  overflow: hidden;
  border: 0;
  border-radius: 18px;
  padding: 14px 16px;
  text-align: left;
  color: inherit;
  background: var(--bg-elevated);
  box-shadow: inset 0 0 0 1px var(--bg-inset);
}

.lapis-lookup-word-main,
.lapis-lookup-word-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.lapis-lookup-word-meta {
  flex: 0 0 auto;
  align-items: flex-end;
  text-align: right;
}

.lapis-lookup-word-main {
  flex: 1 1 auto;
  min-width: 0;
}

.lapis-lookup-word-term {
  font-family: var(--font-serif);
  font-size: 1.2em;
  overflow-wrap: anywhere;
}

.lapis-lookup-word-reading,
.lapis-lookup-word-frequency-source {
  color: var(--fg-subtle);
  font-family: var(--font-sans);
  font-size: 0.85em;
  overflow-wrap: anywhere;
}

.lapis-lookup-word-frequency {
  font-family: var(--font-sans);
  font-size: 1em;
  font-weight: 600;
}

.lapis-lookup-word-detail {
  border-radius: 20px;
  padding: 16px;
  background: var(--bg-elevated);
  box-shadow: inset 0 0 0 1px var(--bg-inset);
  overflow-wrap: anywhere;
  text-align: left;
  line-height: 1.45;
  white-space: normal;
}

.lapis-lookup-word-detail,
.lapis-lookup-word-detail * {
  text-align: left;
}

.lapis-lookup-word-detail .yomitan-glossary ul,
.lapis-lookup-word-detail .yomitan-glossary ol {
  display: block;
  margin: 0 0 0.75em;
  padding-left: 1.25em !important;
}

.lapis-lookup-word-detail .yomitan-glossary li {
  display: list-item;
}

.lapis-lookup-word-detail .yomitan-glossary ul[data-sc-content="glossary"] {
  list-style: disc;
}

.lapis-lookup-word-detail .yomitan-glossary ul[data-sc-content="glossary"] > li::before,
.lapis-lookup-word-detail .yomitan-glossary ul[data-sc-content="glossary"] > li::after {
  content: none !important;
}

.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="extra-info"] > div,
.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="example-sentence"],
.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="example-sentence-a"],
.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="example-sentence-b"],
.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="attribution"] {
  display: block;
}

.lapis-lookup-word-detail .yomitan-glossary [data-sc-content="attribution-footnote"] {
  display: inline;
}

.lapis-lookup-word-detail p,
.lapis-lookup-word-detail ul,
.lapis-lookup-word-detail ol,
.lapis-lookup-word-detail dl,
.lapis-lookup-word-detail blockquote,
.lapis-lookup-word-detail section,
.lapis-lookup-word-detail figure,
.lapis-lookup-word-detail table {
  margin: 0 0 0.75em;
}

.lapis-lookup-word-detail li {
  margin: 0.2em 0 0.2em 1.2em;
}

.lapis-lookup-word-detail br {
  display: block;
  content: "";
  margin-top: 0.35em;
}

.vocab,
.vocab ruby,
.vocab ruby rb,
.vocab ruby rt {
  cursor: pointer;
}

.lapis-lookup-empty {
  color: var(--fg-subtle);
  font-family: var(--font-sans);
  padding: 12px 0;
}

.lapis-lookup-word-detail .yomitan-glossary {
  margin: 0;
}

.lapis-lookup-definition-entry + .lapis-lookup-definition-entry {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--bg-inset);
}

.lapis-lookup-definition-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.lapis-lookup-definition-tag {
  border-radius: 999px;
  padding: 2px 8px;
  background: var(--bg-inset);
  color: var(--fg-subtle);
  font-family: var(--font-sans);
  font-size: 0.78em;
  font-weight: 600;
}
""".strip()

LOOKUP_MARKUP_BLOCK = """
<div id="lapis-lookup-data" class="hidden">{{KanjiLookupData}}</div>
<!-- lapis-lookup-v1 -->
<div id="lapis-lookup-overlay" class="lapis-lookup-overlay hidden">
    <section id="kanji-popover-view" class="lapis-lookup-sheet hidden">
        <div class="lapis-lookup-sheet-header">
            <button type="button" id="lapis-lookup-kanji-back" class="lapis-lookup-back tappable">Back</button>
            <div class="lapis-lookup-sheet-title-wrap">
                <div id="lapis-lookup-kanji-char" class="lapis-lookup-sheet-title"></div>
                <div id="lapis-lookup-kanji-subtitle" class="lapis-lookup-sheet-subtitle"></div>
            </div>
        </div>
        <div id="lapis-lookup-kanji-body" class="lapis-lookup-sheet-body"></div>
    </section>

    <section id="word-popover-view" class="lapis-lookup-sheet hidden">
        <div class="lapis-lookup-sheet-header">
            <button type="button" id="lapis-lookup-word-back" class="lapis-lookup-back tappable">Back</button>
            <div class="lapis-lookup-sheet-title-wrap">
                <div id="lapis-lookup-word-title" class="lapis-lookup-sheet-title"></div>
                <div id="lapis-lookup-word-subtitle" class="lapis-lookup-sheet-subtitle"></div>
            </div>
        </div>
        <div id="lapis-lookup-word-body" class="lapis-lookup-sheet-body"></div>
    </section>
</div>
""".strip()

LOOKUP_SCRIPT_BLOCK = """
<script>
(() => {
    if (window.__lapisLookupInitialized) return;
    window.__lapisLookupInitialized = true;

    function parseLookupData() {
        const dataNode = document.getElementById("lapis-lookup-data");
        if (!dataNode) return null;
        const text = dataNode.textContent?.trim();
        if (!text) return null;
        try {
            return JSON.parse(text);
        } catch (_error) {
            return null;
        }
    }

    function isLookupKanji(character) {
        return /[\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]/.test(character);
    }

    function createLookupStore(lookupData) {
        if (!lookupData || !Array.isArray(lookupData.kanji)) return null;
        const kanjiMap = new Map();
        for (const item of lookupData.kanji) {
            if (!item || !item.char) continue;
            kanjiMap.set(item.char, item);
        }
        return { kanjiMap, currentKanji: null };
    }

    function bindPrimaryActivate(element, handler) {
        if (!element || typeof handler !== "function") return;
        element.classList?.add("tappable");
        if (!element.hasAttribute("onclick")) {
            element.setAttribute("onclick", "");
        }

        let lastTouchTime = 0;
        element.addEventListener("touchend", (event) => {
            lastTouchTime = Date.now();
            handler(event);
        }, { passive: true });

        element.addEventListener("click", (event) => {
            if (Date.now() - lastTouchTime < 500) return;
            handler(event);
        });
    }

    function getEventClientPoint(event) {
        if (typeof event?.clientX === "number" && typeof event?.clientY === "number") {
            return { x: event.clientX, y: event.clientY };
        }

        const touch = event?.changedTouches?.[0] || event?.touches?.[0] || null;
        if (touch && typeof touch.clientX === "number" && typeof touch.clientY === "number") {
            return { x: touch.clientX, y: touch.clientY };
        }

        return null;
    }

    function showLookupSheet(sheetId) {
        const overlay = document.getElementById("lapis-lookup-overlay");
        document.querySelectorAll(".lapis-lookup-sheet").forEach((sheet) => sheet.classList.add("hidden"));
        if (!overlay || !sheetId) {
            overlay?.classList.add("hidden");
            return;
        }
        overlay.classList.remove("hidden");
        document.getElementById(sheetId)?.classList.remove("hidden");
    }

    function closeLookupOverlay(store) {
        if (store) {
            store.currentKanji = null;
        }
        showLookupSheet(null);
    }

    function renderKanjiPopover(store, kanjiItem) {
        const title = document.getElementById("lapis-lookup-kanji-char");
        const subtitle = document.getElementById("lapis-lookup-kanji-subtitle");
        const body = document.getElementById("lapis-lookup-kanji-body");
        if (!title || !subtitle || !body) return;

        title.textContent = kanjiItem.char;
        subtitle.textContent = `${(kanjiItem.relatedWords || []).length} related words`;
        body.innerHTML = "";

        const list = document.createElement("div");
        list.className = "lapis-lookup-word-list";

        for (const relatedWord of kanjiItem.relatedWords || []) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "lapis-lookup-word-row tappable";
            button.addEventListener("click", () => renderWordPopover(store, kanjiItem, relatedWord));

            const left = document.createElement("div");
            left.className = "lapis-lookup-word-main";
            left.innerHTML = `
                <span class="lapis-lookup-word-term">${relatedWord.term}</span>
                ${relatedWord.reading ? `<span class="lapis-lookup-word-reading">${relatedWord.reading}</span>` : ""}
            `;

            const right = document.createElement("div");
            right.className = "lapis-lookup-word-meta";
            if (relatedWord.frequency?.value !== null && relatedWord.frequency?.value !== undefined) {
                right.innerHTML = `
                    <span class="lapis-lookup-word-frequency">${relatedWord.frequency.value}</span>
                    <span class="lapis-lookup-word-frequency-source">${relatedWord.frequency.source || ""}</span>
                `;
            }

            button.appendChild(left);
            button.appendChild(right);
            list.appendChild(button);
        }

        body.appendChild(list.children.length ? list : Object.assign(document.createElement("div"), {
            className: "lapis-lookup-empty",
            textContent: "No related words available."
        }));
        showLookupSheet("kanji-popover-view");
    }

    function renderWordPopover(store, kanjiItem, relatedWord) {
        store.currentKanji = kanjiItem.char;

        const title = document.getElementById("lapis-lookup-word-title");
        const subtitle = document.getElementById("lapis-lookup-word-subtitle");
        const body = document.getElementById("lapis-lookup-word-body");
        if (!title || !subtitle || !body) return;

        title.textContent = relatedWord.term;
        const subtitleParts = [];
        if (relatedWord.reading) subtitleParts.push(relatedWord.reading);
        if (relatedWord.frequency?.value !== null && relatedWord.frequency?.value !== undefined) {
            subtitleParts.push(`${relatedWord.frequency.source || "Frequency"}: ${relatedWord.frequency.value}`);
        }
        subtitle.textContent = subtitleParts.join(" | ");

        body.innerHTML = "";
        const detail = document.createElement("div");
        detail.className = "lapis-lookup-word-detail";
        detail.innerHTML = relatedWord.entryHtml || `<div class="lapis-lookup-empty">No dictionary entry available for ${relatedWord.term}.</div>`;
        body.appendChild(detail);
        showLookupSheet("word-popover-view");
    }

    function enhanceKanjiTargets(store) {
        const vocab = document.querySelector(".vocab");
        if (!vocab || !store) return;
        const targetChars = new Set(store.kanjiMap.keys());
        if (!targetChars.size) return;

        bindPrimaryActivate(vocab, (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            if (target.closest("rt, rp")) return;

            const point = getEventClientPoint(event);
            if (!point) return;

            let textNode = null;
            let offset = 0;

            if (document.caretPositionFromPoint) {
                const position = document.caretPositionFromPoint(point.x, point.y);
                if (position?.offsetNode?.nodeType === Node.TEXT_NODE) {
                    textNode = position.offsetNode;
                    offset = position.offset;
                }
            } else if (document.caretRangeFromPoint) {
                const range = document.caretRangeFromPoint(point.x, point.y);
                if (range?.startContainer?.nodeType === Node.TEXT_NODE) {
                    textNode = range.startContainer;
                    offset = range.startOffset;
                }
            }

            if (!textNode || !vocab.contains(textNode.parentNode)) return;

            const text = textNode.textContent || "";
            const characters = [...text];
            if (!characters.length) return;

            const index = Math.max(0, Math.min(offset, characters.length - 1));
            const character = characters[index];
            if (!character || !targetChars.has(character) || !isLookupKanji(character)) return;

            event.stopPropagation();
            const kanjiItem = store.kanjiMap.get(character);
            if (kanjiItem) {
                renderKanjiPopover(store, kanjiItem);
            }
        });
    }

    function wireNavigation(store) {
        bindPrimaryActivate(document.getElementById("lapis-lookup-kanji-back"), () => closeLookupOverlay(store));
        bindPrimaryActivate(document.getElementById("lapis-lookup-word-back"), () => {
            if (!store?.currentKanji) {
                closeLookupOverlay(store);
                return;
            }
            const kanjiItem = store.kanjiMap.get(store.currentKanji);
            if (!kanjiItem) {
                closeLookupOverlay(store);
                return;
            }
            renderKanjiPopover(store, kanjiItem);
        });
    }

    const store = createLookupStore(parseLookupData());
    if (!store) return;
    enhanceKanjiTargets(store);
    wireNavigation(store);
    closeLookupOverlay(store);
})();
</script>
""".strip()


@dataclass
class BackfillSummary:
    processed: int
    skipped: int
    warnings: list[str]


def reset_debug_log() -> None:
    try:
        LOOKUP_DEBUG_LOG_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass


def debug_log(event: str, **details: Any) -> None:
    try:
        timestamp = datetime.now().isoformat(timespec="seconds")
        lines = [f"[{timestamp}] {event}"]
        for key, value in details.items():
            lines.append(f"  {key}: {value}")
        with LOOKUP_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
            handle.write("\n\n")
    except Exception:
        pass


def preview_text(value: Any, limit: int = LOOKUP_DEBUG_PREVIEW_LIMIT) -> str:
    text = str(value)
    text = text.replace("\n", "\\n")
    return text[:limit]


def payload_diagnostics(value: str) -> dict[str, Any]:
    return {
        "length": len(value),
        "contains_backslash_quote_amp": '\\&quot;' in value,
        "contains_literal_amp_quot": '&quot;' in value,
        "contains_escaped_quote": '\\"' in value,
        "entry_html_index": value.find('"entryHtml"'),
        "preview": preview_text(value),
    }


def preview_first_entry_html(payload: dict[str, Any]) -> str:
    for kanji_item in payload.get("kanji", []):
        for related_word in kanji_item.get("relatedWords", []):
            entry_html = related_word.get("entryHtml")
            if isinstance(entry_html, str):
                return preview_text(entry_html)
    return "<no entryHtml>"


def decode_transport_payload(value: str) -> str:
    return html.unescape(value)


def read_raw_lookup_field_from_db(col: Any, note_id: int) -> str:
    row = col.db.first("select flds from notes where id = ?", note_id)
    if not row:
        return ""
    fields = row[0].split("\x1f")
    try:
        field_ord = next(
            index
            for index, field in enumerate(col.get_note(note_id).note_type()["flds"])
            if field["name"] == LOOKUP_FIELD_NAME
        )
    except StopIteration:
        return ""
    return fields[field_ord] if field_ord < len(fields) else ""


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

    reset_debug_log()
    debug_log("setup_and_backfill_selected_notes:start", note_ids=note_ids[:20], total_notes=len(note_ids))

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
                f"Template patched: {'yes' if template_marked else 'no'}",
                f"Lookup payload length: {payload_length}",
                f"Lookup payload has \\\\&quot;: {'yes' if has_lookup_field and '\\&quot;' in note[LOOKUP_FIELD_NAME] else 'no'}",
                "",
            ]
        )

    lines.extend(
        [
            f"Debug log: {LOOKUP_DEBUG_LOG_PATH}",
            "",
        ]
    )
    showInfo("\n".join(lines).strip(), parent=browser)


def run_setup_and_backfill(col: Any, note_ids: Sequence[int], config: dict[str, Any]) -> BackfillSummary:
    model_id = col.models.get_single_notetype_of_notes(note_ids)
    model = col.models.get(model_id)
    if not is_lapis_model(model):
        raise ValueError("Selected notes are not on a supported Lapis-family note type.")

    debug_log("run_setup_and_backfill:start", note_ids=list(note_ids)[:20], total_notes=len(note_ids), model_name=model["name"])

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
        debug_log(
            "run_setup_and_backfill:before_store",
            note_id=note_id,
            expression=note["Expression"],
            payload_diagnostics=payload_diagnostics(serialized_payload),
            entry_html_preview=preview_first_entry_html(item["payload"]),
        )
        escaped_payload = html.escape(serialized_payload, quote=False)
        note[LOOKUP_FIELD_NAME] = escaped_payload
        col.update_note(note, skip_undo_entry=True)
        stored_payload = col.get_note(note_id)[LOOKUP_FIELD_NAME]
        raw_db_payload = read_raw_lookup_field_from_db(col, note_id)
        debug_log(
            "run_setup_and_backfill:after_store",
            note_id=note_id,
            payload_diagnostics=payload_diagnostics(stored_payload),
            decoded_payload_diagnostics=payload_diagnostics(decode_transport_payload(stored_payload)),
            changed_after_store=decode_transport_payload(stored_payload) != serialized_payload,
            raw_db_payload_diagnostics=payload_diagnostics(raw_db_payload),
            raw_db_decoded_payload_diagnostics=payload_diagnostics(decode_transport_payload(raw_db_payload)),
            changed_in_db=decode_transport_payload(raw_db_payload) != serialized_payload,
        )
        processed += 1
        warnings.extend(item.get("warnings", []))

    debug_log("run_setup_and_backfill:done", processed=processed, skipped=skipped, warnings_count=len(warnings))
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
    patch_lookup_css(cloned, force=True)
    for template in cloned["tmpls"]:
        patch_lookup_template(template, force=True)
    col.models.add(cloned)
    return cloned


def refresh_lookup_model(col: Any, model: dict[str, Any]) -> None:
    changed = patch_lookup_css(model, force=True)
    for template in model["tmpls"]:
        changed = patch_lookup_template(template, force=True) or changed
    if changed:
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


def patch_lookup_css(model: dict[str, Any], force: bool = False) -> bool:
    css = model["css"]
    marker = "/* lapis-lookup-v1 */"
    if not force and LOOKUP_TEMPLATE_MARKER in css:
        return False
    if marker in css:
        css = re.sub(r"\n*/\* lapis-lookup-v1 \*/.*\Z", "", css, count=1, flags=re.S).rstrip()
    model["css"] = f"{css}\n\n{LOOKUP_CSS_BLOCK}\n" if css else f"{LOOKUP_CSS_BLOCK}\n"
    return True


def patch_lookup_template(template: dict[str, Any], force: bool = False) -> bool:
    afmt = template["afmt"]
    changed = False
    if force:
        start = afmt.find('<script id="lapis-lookup-data"')
        if start == -1:
            start = afmt.find('<div id="lapis-lookup-data"')
        if start == -1:
            start = afmt.find('<!-- lapis-lookup-v1 -->')
        if start != -1:
            image_modal = "<!------- Image modal --------->"
            end = afmt.find(image_modal, start)
            if end != -1:
                afmt = f"{afmt[:start].rstrip()}\n\n    {afmt[end:]}"
            else:
                afmt = afmt[:start].rstrip()
            changed = True

        new_afmt = re.sub(
            r'\s*<script>\s*\(\(\) => \{\s*if \(window\.__lapisLookupInitialized\) return;.*?</script>\s*\Z',
            "",
            afmt,
            count=1,
            flags=re.S,
        )
        if new_afmt != afmt:
            afmt = new_afmt
            changed = True
    elif LOOKUP_TEMPLATE_MARKER in afmt:
        return False

    if "<!------- Image modal --------->" in afmt:
        afmt = afmt.replace("<!------- Image modal --------->", f"{LOOKUP_MARKUP_BLOCK}\n\n    <!------- Image modal --------->", 1)
    else:
        afmt = f"{afmt.rstrip()}\n\n{LOOKUP_MARKUP_BLOCK}\n"

    afmt = f"{afmt.rstrip()}\n\n{LOOKUP_SCRIPT_BLOCK}\n"
    template["afmt"] = afmt
    return True


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
    debug_log(
        "run_lookup_cli:completed",
        returncode=completed.returncode,
        node=node,
        cli_path=cli_path,
        stdout_diagnostics=payload_diagnostics(completed.stdout),
        stderr_preview=preview_text(completed.stderr),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Lookup CLI failed.")

    parsed = json.loads(completed.stdout)
    if parsed.get("results"):
        first_payload = parsed["results"][0].get("payload", {})
        debug_log(
            "run_lookup_cli:parsed",
            results_count=len(parsed["results"]),
            first_entry_html_preview=preview_first_entry_html(first_payload),
            first_payload_diagnostics=payload_diagnostics(
                json.dumps(first_payload, ensure_ascii=False, separators=(",", ":"))
            ),
        )
    return parsed


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
