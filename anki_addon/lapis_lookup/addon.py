from __future__ import annotations

import json
import os
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

LOOKUP_CSS_BLOCK = """
/* lapis-lookup-v1 */
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
  align-items: flex-end;
  text-align: right;
}

.lapis-lookup-word-term {
  font-family: var(--font-serif);
  font-size: 1.2em;
}

.lapis-lookup-word-reading,
.lapis-lookup-word-frequency-source {
  color: var(--fg-subtle);
  font-family: var(--font-sans);
  font-size: 0.85em;
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
<script id="lapis-lookup-data" type="application/json">{{text:KanjiLookupData}}</script>
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
        const textNodes = [];
        const walker = document.createTreeWalker(vocab, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parentTag = node.parentElement?.tagName;
                if (parentTag === "RT" || parentTag === "RP") {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            },
        });

        let currentNode = walker.nextNode();
        while (currentNode) {
            textNodes.push(currentNode);
            currentNode = walker.nextNode();
        }

        for (const node of textNodes) {
            const text = node.textContent || "";
            if (![...text].some((character) => targetChars.has(character) && isLookupKanji(character))) continue;

            const fragment = document.createDocumentFragment();
            for (const character of text) {
                if (targetChars.has(character) && isLookupKanji(character)) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "lapis-lookup-kanji-target tappable";
                    button.textContent = character;
                    button.addEventListener("click", (event) => {
                        event.stopPropagation();
                        const kanjiItem = store.kanjiMap.get(character);
                        if (kanjiItem) {
                            renderKanjiPopover(store, kanjiItem);
                        }
                    });
                    fragment.appendChild(button);
                } else {
                    fragment.appendChild(document.createTextNode(character));
                }
            }
            node.parentNode?.replaceChild(fragment, node);
        }
    }

    function wireNavigation(store) {
        document.getElementById("lapis-lookup-kanji-back")?.addEventListener("click", () => closeLookupOverlay(store));
        document.getElementById("lapis-lookup-word-back")?.addEventListener("click", () => {
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


def init() -> None:
    gui_hooks.browser_menus_did_init.append(add_browser_menu)


def add_browser_menu(browser: Browser) -> None:
    menu = QMenu("Lapis Lookup", browser)
    browser.form.menubar.addMenu(menu)

    setup_action = QAction("Setup + Backfill Selected Notes", browser)
    qconnect(setup_action.triggered, lambda: setup_and_backfill_selected_notes(browser))
    menu.addAction(setup_action)

    diagnose_action = QAction("Diagnose Selected Notes", browser)
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

    if not is_lookup_enabled_model(model) and not mw.confirm_schema_modification():
        return

    QueryOp(
        parent=browser,
        op=lambda col: run_setup_and_backfill(col, note_ids, load_config()),
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
                "",
            ]
        )

    showInfo("\n".join(lines).strip(), parent=browser)


def run_setup_and_backfill(col: Any, note_ids: Sequence[int], config: dict[str, Any]) -> BackfillSummary:
    model_id = col.models.get_single_notetype_of_notes(note_ids)
    model = col.models.get(model_id)
    if not is_lapis_model(model):
        raise ValueError("Selected notes are not on a supported Lapis-family note type.")

    target_model = model
    if not is_lookup_enabled_model(model):
        target_model = clone_lookup_model(col, model)
        convert_notes_to_model(col, note_ids, model, target_model)

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

        note[LOOKUP_FIELD_NAME] = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
        note.flush()
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


def clone_lookup_model(col: Any, model: dict[str, Any]) -> dict[str, Any]:
    cloned = col.models.copy(model, add=False)
    cloned["name"] = unique_lookup_model_name(col, model["name"])
    ensure_lookup_field(col, cloned)
    patch_lookup_css(cloned)
    for template in cloned["tmpls"]:
        patch_lookup_template(template)
    col.models.add(cloned)
    return cloned


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


def patch_lookup_css(model: dict[str, Any]) -> None:
    if LOOKUP_TEMPLATE_MARKER in model["css"]:
        return
    model["css"] = f"{model['css'].rstrip()}\n\n{LOOKUP_CSS_BLOCK}\n"


def patch_lookup_template(template: dict[str, Any]) -> None:
    afmt = template["afmt"]
    if LOOKUP_TEMPLATE_MARKER in afmt:
        return

    if "<!------- Image modal --------->" in afmt:
        afmt = afmt.replace("<!------- Image modal --------->", f"{LOOKUP_MARKUP_BLOCK}\n\n    <!------- Image modal --------->", 1)
    else:
        afmt = f"{afmt.rstrip()}\n\n{LOOKUP_MARKUP_BLOCK}\n"

    afmt = f"{afmt.rstrip()}\n\n{LOOKUP_SCRIPT_BLOCK}\n"
    template["afmt"] = afmt


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

    node = shutil.which("node")
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
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Both node and npm must be installed and available on PATH.")

    if not cli_path.exists():
        install_command = ["npm", "ci"] if (tool_root / "package-lock.json").exists() else ["npm", "install"]
        run_command(install_command, tool_root)
        run_command(["npm", "run", "build"], tool_root)

    cache_dir = tool_root.parent.parent / ".cache" / "yomitan-dicts"
    required_archives = {
        "jitendex-yomitan.zip",
        "KANJIDIC_english.zip",
        "JPDB_v2.2_Frequency_Kana_2024-10-13.zip",
        "JPDB_Kanji.zip",
    }
    if not cache_dir.exists() or any(not (cache_dir / file_name).exists() for file_name in required_archives):
        if not fetch_path.exists():
            run_command(["npm", "run", "build"], tool_root)
        run_command([node, str(fetch_path)], tool_root)


def run_command(command: Sequence[str], cwd: Path) -> None:
    env = os.environ.copy()
    env["npm_config_registry"] = "https://registry.npmjs.org/"
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Command failed: {' '.join(command)}")


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
