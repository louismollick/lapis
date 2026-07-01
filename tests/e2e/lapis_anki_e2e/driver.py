from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

import aqt
from anki.import_export_pb2 import ImportAnkiPackageRequest
from aqt import gui_hooks
from aqt.qt import QApplication, QEventLoop, QTimer
from aqt.browser.previewer import Previewer

from lapis_anki_e2e.debug_config import (
    DEBUG_CONTINUE_FILE_NAME,
    devtools_url,
    parse_pause_at,
    sanitize_phase_name,
)
from lapis_anki_e2e.fixture_data import (
    CANONICAL_MODEL_NAME,
    FIXTURE_DECK_NAME,
    LAPIS_MODEL_NAME,
    LEGACY_MODEL_NAME,
    build_stub_lookup_results,
    expected_ui_assertions,
    scenario_for_expression,
)


RUN_STARTED = False
PREVIEW_SCRIPT_SETTLE_MS = 3500


def main_window() -> Any:
    return aqt.mw


def write_report(report_path: Path, report: dict[str, Any]) -> None:
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_debug_settings(artifacts_dir: Path) -> dict[str, Any]:
    enabled = os.environ.get("LAPIS_E2E_DEBUG_WEBVIEW") == "1"
    port_text = os.environ.get("LAPIS_E2E_DEBUG_PORT", "").strip()
    port = int(port_text) if port_text else None
    return {
        "enabled": enabled,
        "port": port,
        "pauseAt": parse_pause_at(os.environ.get("LAPIS_E2E_DEBUG_PAUSE_AT")),
        "keepOpen": os.environ.get("LAPIS_E2E_DEBUG_KEEP_OPEN") == "1",
        "devtoolsUrl": os.environ.get("LAPIS_E2E_DEBUG_DEVTOOLS_URL", "").strip()
        or (devtools_url(port) if port else None),
        "continuePath": artifacts_dir / DEBUG_CONTINUE_FILE_NAME,
        "currentPause": None,
    }


def sync_debug_report(report: dict[str, Any], debug: dict[str, Any]) -> None:
    report["debug"] = {
        "enabled": debug["enabled"],
        "port": debug["port"],
        "pauseAt": list(debug["pauseAt"]),
        "currentPause": debug["currentPause"],
        "devtoolsUrl": debug["devtoolsUrl"],
    }


class FixedCardPreviewer(Previewer):
    def __init__(self, card: Any) -> None:
        self._card = card
        self._last_card_id = 0
        super().__init__(parent=None, mw=main_window(), on_close=lambda: None)

    def card(self) -> Any:
        return self._card

    def card_changed(self) -> bool:
        card = self.card()
        if not card:
            return True
        changed = card.id != self._last_card_id
        self._last_card_id = card.id
        return changed

    def set_card(self, card: Any) -> None:
        self._card = card
        self._card_changed = True

    def show_answer(self) -> None:
        # Previewer._render_scheduled resets _state to "question" when _card_changed
        # is true, so answer-side rendering must clear that flag first.
        self._state = "answer"
        self._last_state = None
        self._card_changed = False
        self.cancel_timer()
        from aqt import sound

        original_play_tags = sound.av_player.play_tags

        def skip_preview_audio(*_args: Any, **_kwargs: Any) -> None:
            return None

        sound.av_player.play_tags = skip_preview_audio
        try:
            self._render_scheduled()
        finally:
            sound.av_player.play_tags = original_play_tags

    def open(self) -> None:
        self._state = "answer"
        self._last_state = None
        self._open = True
        self._create_gui()
        self._setup_web_view()
        self.show()
        self.show_answer()


def init_driver() -> None:
    if os.environ.get("LAPIS_E2E_DRIVER") != "1":
        return
    gui_hooks.profile_did_open.append(schedule_run)
    if getattr(main_window(), "col", None) is not None:
        schedule_run()


def schedule_run() -> None:
    global RUN_STARTED
    if RUN_STARTED:
        return
    RUN_STARTED = True
    QTimer.singleShot(0, run_harness)


def run_harness() -> None:
    report_path = Path(os.environ["LAPIS_E2E_REPORT"])
    artifacts_dir = Path(os.environ["LAPIS_E2E_ARTIFACTS"])
    debug = load_debug_settings(artifacts_dir)
    report: dict[str, Any] = {
        "status": "failed",
        "phase": "starting",
        "deck": FIXTURE_DECK_NAME,
        "notes": {},
        "errors": [],
    }
    sync_debug_report(report, debug)
    try:
        fixture_path = Path(os.environ["LAPIS_E2E_FIXTURE"])
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        write_report(report_path, report)

        report["phase"] = "import-fixture"
        import_log = import_fixture(fixture_path)
        report["fixtureImport"] = {
            "newCount": len(getattr(import_log.log, "new", [])),
            "updatedCount": len(getattr(import_log.log, "updated", [])),
        }
        write_report(report_path, report)

        lookup_addon = __import__("lapis_lookup.addon", fromlist=["addon"])
        lookup_store = __import__("lapis_lookup.lookup_store", fromlist=["lookup_store"])

        report["phase"] = "classify-fixture-notes"
        note_ids_by_label = classify_fixture_notes(lookup_addon)
        for label, (note_id, details) in note_ids_by_label.items():
            report["notes"][label] = {
                "noteId": note_id,
                "expression": details["expression"],
                "fixtureImport": {"imported": True},
                "models": {
                    "before": {
                        "id": details["modelId"],
                        "name": details["modelName"],
                    },
                },
                "previewPhases": [],
                "debugArtifacts": [],
            }
        write_report(report_path, report)
        note_ids_by_expression = {
            details["expression"]: note_id
            for note_id, details in note_ids_by_label.values()
        }
        note_ids = [note_id for note_id, _details in note_ids_by_label.values()]
        report["phase"] = "build-lookup-items"
        lookup_items = lookup_addon.build_lookup_items(note_ids, main_window().col)
        report["lookupItems"] = lookup_items

        report["phase"] = "apply-backfill-results"
        stub_results = build_stub_lookup_results(lookup_addon, lookup_items)
        summary = lookup_addon.apply_backfill_results(main_window().col, stub_results)
        backfill_items_by_note = {
            int(item["noteId"]): item for item in stub_results["results"]
        }
        report["backfill"] = {
            "processed": summary.processed,
            "converted": summary.converted,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "warnings": summary.warnings,
            "failures": summary.failures,
            "invariantViolations": summary.invariant_violations,
        }
        write_report(report_path, report)
        if summary.failed or summary.invariant_violations:
            raise RuntimeError(lookup_addon.format_backfill_failure_report(summary))

        report["phase"] = "validate-lookup-media"
        media_report = validate_lookup_media(lookup_store, note_ids_by_expression)
        report["media"] = media_report
        write_report(report_path, report)

        preview_context = {
            "report_path": report_path,
            "artifacts_dir": artifacts_dir,
            "report": report,
            "debug": debug,
            "lookup_addon": lookup_addon,
            "media_report": media_report,
            "backfill_items_by_note": backfill_items_by_note,
            "note_ids_by_label": note_ids_by_label,
            "preview_items": list(ordered_preview_items(note_ids_by_label).items()),
            "preview_index": 0,
        }
        report["phase"] = "preview-async"
        write_report(report_path, report)
        QTimer.singleShot(0, lambda: run_next_preview(preview_context))
        return
    except Exception as error:
        report["errors"].append(str(error))
        report["traceback"] = traceback.format_exc()
    finally:
        if report.get("phase") != "preview-async":
            finish_harness(report_path, report, artifacts_dir, debug)


def finish_harness(
    report_path: Path,
    report: dict[str, Any],
    artifacts_dir: Path,
    debug: dict[str, Any],
) -> None:
    if debug["enabled"] and debug["keepOpen"]:
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=None,
            debug=debug,
            previewer=None,
            label=None,
            pause_phase="session-complete" if report.get("status") == "ok" else "session-failed",
            artifacts_dir=artifacts_dir,
            force=True,
        )
    write_report(report_path, report)
    QTimer.singleShot(0, finalize_app)


def run_next_preview(context: dict[str, Any]) -> None:
    report_path: Path = context["report_path"]
    report: dict[str, Any] = context["report"]
    artifacts_dir: Path = context["artifacts_dir"]
    debug: dict[str, Any] = context["debug"]
    preview_items: list[tuple[str, tuple[int, dict[str, Any]]]] = context["preview_items"]
    preview_index: int = context["preview_index"]

    try:
        if preview_index >= len(preview_items):
            for label, (note_id, _details) in context["note_ids_by_label"].items():
                note = main_window().col.get_note(note_id)
                note_report = report["notes"][label]
                note_report.setdefault("models", {}).setdefault(
                    "after",
                    {"id": note.note_type()["id"], "name": note.note_type()["name"]},
                )
            report["status"] = "ok"
            report["phase"] = "done"
            finish_harness(report_path, report, artifacts_dir, debug)
            return

        label, (note_id, details) = preview_items[preview_index]
        lookup_addon = context["lookup_addon"]
        media_report = context["media_report"]
        backfill_items_by_note = context["backfill_items_by_note"]

        note = main_window().col.get_note(note_id)
        note_report = report["notes"][label]
        note_report["backfillResult"] = {
            "status": backfill_items_by_note[note_id]["status"],
            "mode": backfill_items_by_note[note_id]["mode"],
            "warnings": backfill_items_by_note[note_id]["warnings"],
        }
        note_report["models"]["after"] = {
            "id": note.note_type()["id"],
            "name": note.note_type()["name"],
        }
        note_report["payloadPresent"] = bool(lookup_addon.note_lookup_payload_text(note).strip())
        note_report["lookupStoreMedia"] = media_report["notes"][details["expression"]]
        if note.note_type()["name"] != CANONICAL_MODEL_NAME:
            raise RuntimeError(f"{label} note did not convert to {CANONICAL_MODEL_NAME}")

        report["phase"] = f"preview-{label}"
        write_report(report_path, report)

        card = main_window().col.get_card(main_window().col.find_cards(f"nid:{note_id}")[0])
        previewer = FixedCardPreviewer(card)
        context["previewer"] = previewer
        context["label"] = label
        context["expression"] = details["expression"]
        context["note_report"] = note_report
        previewer.open()
        QTimer.singleShot(PREVIEW_SCRIPT_SETTLE_MS, lambda: continue_preview_note(context))
    except Exception as error:
        report["errors"].append(str(error))
        report["traceback"] = traceback.format_exc()
        finish_harness(report_path, report, artifacts_dir, debug)


def continue_preview_note(context: dict[str, Any]) -> None:
    report_path: Path = context["report_path"]
    report: dict[str, Any] = context["report"]
    artifacts_dir: Path = context["artifacts_dir"]
    debug: dict[str, Any] = context["debug"]
    previewer: FixedCardPreviewer = context["previewer"]

    try:
        preview_report = preview_note(
            previewer=previewer,
            label=context["label"],
            expression=context["expression"],
            artifacts_dir=artifacts_dir,
            report=report,
            report_path=report_path,
            note_report=context["note_report"],
            debug=debug,
        )
        context["note_report"]["preview"] = preview_report
        write_report(report_path, report)
    except Exception as error:
        report["errors"].append(str(error))
        report["traceback"] = traceback.format_exc()
        finish_harness(report_path, report, artifacts_dir, debug)
        return
    finally:
        previewer.close()

    context["preview_index"] += 1
    QTimer.singleShot(0, lambda: run_next_preview(context))


def finalize_app() -> None:
    window = main_window()
    if window is not None:
        window.close()
    app = QApplication.instance()
    if app is not None:
        app.quit()


def mark_preview_phase(
    *,
    report_path: Path,
    report: dict[str, Any],
    note_report: dict[str, Any],
    label: str,
    phase: str,
) -> None:
    note_report.setdefault("previewPhases", []).append(phase)
    report["phase"] = f"preview-{label}:{phase}"
    write_report(report_path, report)


def import_fixture(fixture_path: Path) -> Any:
    options = main_window().col._backend.get_import_anki_package_presets()
    request = ImportAnkiPackageRequest(
        package_path=str(fixture_path),
        options=options,
    )
    return main_window().col.import_anki_package(request)


def classify_fixture_notes(lookup_addon: Any) -> dict[str, tuple[int, dict[str, Any]]]:
    note_ids = [int(note_id) for note_id in main_window().col.db.list("select id from notes")]
    notes: dict[str, tuple[int, dict[str, str]]] = {}
    for note_id in note_ids:
        note = main_window().col.get_note(note_id)
        model_name = note.note_type()["name"]
        expression = (
            note["Expression"]
            if lookup_addon.note_has_field(note, "Expression")
            else lookup_addon.extract_sort_field_expression(note)
        )
        if model_name == LAPIS_MODEL_NAME:
            notes["lapis"] = (
                note_id,
                {
                    "modelId": note.note_type()["id"],
                    "modelName": model_name,
                    "expression": expression,
                },
            )
        elif model_name == LEGACY_MODEL_NAME:
            notes["legacy"] = (
                note_id,
                {
                    "modelId": note.note_type()["id"],
                    "modelName": model_name,
                    "expression": expression,
                },
            )
    if set(notes) != {"lapis", "legacy"}:
        raise RuntimeError(f"Expected one Lapis and one legacy note, got: {notes}")
    return notes


def ordered_preview_items(
    note_ids_by_label: dict[str, tuple[int, dict[str, Any]]],
) -> dict[str, tuple[int, dict[str, Any]]]:
    order_name = os.environ.get("LAPIS_E2E_PREVIEW_ORDER", "lapis-first")
    labels = ["legacy", "lapis"] if order_name == "legacy-first" else ["lapis", "legacy"]
    return {label: note_ids_by_label[label] for label in labels}


def validate_lookup_media(lookup_store: Any, note_ids_by_expression: dict[str, int]) -> dict[str, Any]:
    manifest_path = lookup_store.lookup_store_media_path(main_window().col)
    if manifest_path is None or not manifest_path.exists():
        raise RuntimeError("Lookup store manifest was not written.")

    per_note: dict[str, Any] = {}
    all_missing: list[str] = []
    all_expected_shards: set[str] = set()

    for expression in note_ids_by_expression:
        scenario = scenario_for_expression(expression)
        expected_terms = sorted(set(scenario["shared_terms"]) | set(word_ref for item in scenario["payload"]["kanji"] for word_ref in item["wordRefs"]))
        expected_shards = sorted(
            {
                lookup_store.lookup_store_shard_media_name(lookup_store.lookup_term_shard(term))
                for term in expected_terms
            }
        )
        missing = [
            shard_name
            for shard_name in expected_shards
            if not (manifest_path.parent / shard_name).exists()
        ]
        all_expected_shards.update(expected_shards)
        all_missing.extend(missing)
        per_note[expression] = {
            "manifestPresent": True,
            "expectedTerms": expected_terms,
            "expectedShards": expected_shards,
            "missingShards": missing,
        }
    if all_missing:
        raise RuntimeError(f"Missing lookup store shards: {sorted(set(all_missing))}")

    return {
        "manifestPath": str(manifest_path),
        "manifestExists": True,
        "expectedShards": sorted(all_expected_shards),
        "missingShards": sorted(set(all_missing)),
        "notes": per_note,
    }


def preview_note(
    *,
    previewer: FixedCardPreviewer,
    label: str,
    expression: str,
    artifacts_dir: Path,
    report: dict[str, Any],
    report_path: Path,
    note_report: dict[str, Any],
    debug: dict[str, Any],
) -> dict[str, Any]:
    try:
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="previewer-ready",
        )
        web = previewer._web
        assert web is not None
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-preview-open",
            artifacts_dir=artifacts_dir,
        )

        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="render-answer",
        )
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-preview-render",
            artifacts_dir=artifacts_dir,
        )
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="wait-for-targets",
        )
        wait_for_condition(
            web,
            f"""
(() => {{
  const dataText = document.getElementById("lapis-lookup-data")?.textContent || "";
  let data = null;
  try {{
    data = JSON.parse(dataText);
  }} catch (error) {{
    return false;
  }}
  return data?.expression === {expression!r} &&
    Boolean(window.__lapisLookupStoreManifest) &&
    document.querySelectorAll(".lapis-lookup-kanji-target").length > 0;
}})()
""",
            f"lookup targets for {label}",
        )
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="install-probe",
        )
        install_probe(web)
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-targets-ready",
            artifacts_dir=artifacts_dir,
        )

        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="click-kanji",
        )
        click_web_selector(
            web,
            ".lapis-lookup-kanji-target",
            f"{label} kanji target",
        )
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-kanji-click",
            artifacts_dir=artifacts_dir,
        )
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="wait-for-kanji-overlay",
        )
        wait_for_overlay_state(
            web,
            label=label,
            overlay_selector="#lapis-lookup-overlay",
            view_selector="#kanji-popover-view",
            description="kanji overlay",
        )
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-kanji-overlay",
            artifacts_dir=artifacts_dir,
        )

        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="click-related-word",
        )
        click_web_selector(
            web,
            ".lapis-lookup-word-row",
            f"{label} related word row",
        )
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-related-word-click",
            artifacts_dir=artifacts_dir,
        )
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="wait-for-word-overlay",
        )
        wait_for_overlay_state(
            web,
            label=label,
            overlay_selector="#lapis-lookup-overlay",
            view_selector="#word-popover-view",
            description="word overlay",
        )
        maybe_pause_debug(
            report_path=report_path,
            report=report,
            note_report=note_report,
            debug=debug,
            previewer=previewer,
            label=label,
            pause_phase="after-word-overlay",
            artifacts_dir=artifacts_dir,
        )

        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="collect-snapshot",
        )
        snapshot = eval_js(
            web,
            """
(() => {
  return {
    targetCount: document.querySelectorAll(".lapis-lookup-kanji-target").length,
    clickedKanji: document.querySelector("#lapis-lookup-kanji-char")?.textContent?.trim() || "",
    components: [...document.querySelectorAll(".lapis-lookup-component-chip")].map(node => node.textContent.trim()),
    relatedRows: document.querySelectorAll(".lapis-lookup-word-row").length,
    frequencySource: document.querySelector(".lapis-lookup-word-frequency-source")?.textContent?.trim() || "",
    wordTitleHtml: document.querySelector("#lapis-lookup-word-title")?.innerHTML || "",
    wordSubtitleText: document.querySelector("#lapis-lookup-word-subtitle")?.textContent?.trim() || "",
    wordBodyHtml: document.querySelector("#lapis-lookup-word-body")?.innerHTML || "",
    consoleErrors: window.__lapisE2E?.consoleErrors || [],
    windowErrors: window.__lapisE2E?.windowErrors || [],
    rejections: window.__lapisE2E?.rejections || [],
  };
})()
""",
        )
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="assert-snapshot",
        )
        assertions = assert_preview(snapshot, expression)
        mark_preview_phase(
            report_path=report_path,
            report=report,
            note_report=note_report,
            label=label,
            phase="done",
        )
        return {
            "loadSuccess": True,
            "targetCount": snapshot["targetCount"],
            "clickedKanji": snapshot["clickedKanji"],
            "components": snapshot["components"],
            "relatedRows": snapshot["relatedRows"],
            "frequencySource": snapshot["frequencySource"],
            "wordTitleHtml": snapshot["wordTitleHtml"],
            "wordSubtitleText": snapshot["wordSubtitleText"],
            "wordBodyHtml": snapshot["wordBodyHtml"],
            "jsErrors": {
                "console": snapshot["consoleErrors"],
                "window": snapshot["windowErrors"],
                "rejections": snapshot["rejections"],
            },
            "kanjiClickAssertions": assertions["kanjiClickAssertions"],
            "relatedWordClickAssertions": assertions["relatedWordClickAssertions"],
        }
    except Exception:
        if previewer is not None:
            capture_failure_artifacts(previewer, artifacts_dir, label)
            maybe_pause_debug(
                report_path=report_path,
                report=report,
                note_report=note_report,
                debug=debug,
                previewer=previewer,
                label=label,
                pause_phase="failure",
                artifacts_dir=artifacts_dir,
                force=debug["keepOpen"],
            )
        raise
    finally:
        pass


def install_probe(web: Any) -> None:
    page = web.page()
    assert page is not None
    page.runJavaScript(
        """
(() => {
  window.__lapisE2E = window.__lapisE2E || {
    consoleErrors: [],
    windowErrors: [],
    rejections: [],
  };
  window.__lapisE2E.consoleErrors = [];
  window.__lapisE2E.windowErrors = [];
  window.__lapisE2E.rejections = [];
  if (!window.__lapisE2E.installed) {
    window.__lapisE2E.installed = true;
    const originalConsoleError = console.error.bind(console);
    console.error = (...args) => {
      window.__lapisE2E.consoleErrors.push(args.map(value => String(value)).join(" "));
      return originalConsoleError(...args);
    };
    window.addEventListener("error", event => {
      window.__lapisE2E.windowErrors.push(String(event.message || event.error || "error"));
    });
    window.addEventListener("unhandledrejection", event => {
      window.__lapisE2E.rejections.push(String(event.reason || "unhandledrejection"));
    });
  }
  return true;
})()
""",
    )


def assert_preview(snapshot: dict[str, Any], expression: str) -> dict[str, Any]:
    expected = expected_ui_assertions()[expression]
    if snapshot["targetCount"] < 1:
        raise RuntimeError(f"{expression}: no clickable kanji targets")
    if snapshot["clickedKanji"] != expected["clicked_kanji"]:
        raise RuntimeError(
            f"{expression}: expected kanji {expected['clicked_kanji']}, got {snapshot['clickedKanji']}"
        )
    if snapshot["components"] != expected["components"]:
        raise RuntimeError(
            f"{expression}: expected components {expected['components']}, got {snapshot['components']}"
        )
    if snapshot["relatedRows"] != expected["related_rows"]:
        raise RuntimeError(
            f"{expression}: expected {expected['related_rows']} related rows, got {snapshot['relatedRows']}"
        )
    if snapshot["frequencySource"] != expected["frequency_source"]:
        raise RuntimeError(
            f"{expression}: expected frequency source {expected['frequency_source']}, got {snapshot['frequencySource']}"
        )
    if expected["first_related_term"] not in snapshot["wordTitleHtml"]:
        raise RuntimeError(
            f"{expression}: expected related term {expected['first_related_term']} in {snapshot['wordTitleHtml']}"
        )
    if not snapshot["wordBodyHtml"].strip():
        raise RuntimeError(f"{expression}: empty dictionary definition body")
    if snapshot["consoleErrors"] or snapshot["windowErrors"] or snapshot["rejections"]:
        raise RuntimeError(
            f"{expression}: JS errors detected: "
            f"{snapshot['consoleErrors']} {snapshot['windowErrors']} {snapshot['rejections']}"
        )
    return {
        "kanjiClickAssertions": {
            "passed": True,
            "expectedKanji": expected["clicked_kanji"],
            "actualKanji": snapshot["clickedKanji"],
            "expectedComponents": expected["components"],
            "actualComponents": snapshot["components"],
        },
        "relatedWordClickAssertions": {
            "passed": True,
            "expectedRelatedRows": expected["related_rows"],
            "actualRelatedRows": snapshot["relatedRows"],
            "expectedFrequencySource": expected["frequency_source"],
            "actualFrequencySource": snapshot["frequencySource"],
            "expectedFirstRelatedTerm": expected["first_related_term"],
            "actualWordTitleHtml": snapshot["wordTitleHtml"],
            "definitionNonEmpty": bool(snapshot["wordBodyHtml"].strip()),
        },
    }


def eval_js(web: Any, script: str, timeout_ms: int = 10000) -> Any:
    loop = QEventLoop()
    state: dict[str, Any] = {"done": False, "value": None}

    def on_result(value: Any) -> None:
        state["done"] = True
        state["value"] = value
        if loop.isRunning():
            loop.quit()

    timer = QTimer(main_window())
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    run_web_javascript(web, script, on_result)
    loop.exec()
    timer.stop()
    if not state["done"]:
        raise TimeoutError(f"Timed out waiting for JS result: {script[:120]}")
    return state["value"]


def run_web_javascript(web: Any, script: str, callback: Any) -> None:
    runner = getattr(web, "evalWithCallback", None)
    if callable(runner):
        runner(script, callback)
        return
    page = web.page()
    assert page is not None
    page.runJavaScript(script, callback)


def wait_for_condition(web: Any, script: str, label: str, timeout_ms: int = 60000) -> None:
    loop = QEventLoop()
    state: dict[str, Any] = {"done": False, "last_value": None}

    def finish() -> None:
        if loop.isRunning():
            loop.quit()

    timer = QTimer(main_window())
    timer.setSingleShot(True)
    timer.timeout.connect(finish)
    timer.start(timeout_ms)

    def poll() -> None:
        if state["done"]:
            return

        def on_result(value: Any) -> None:
            state["last_value"] = value
            if value:
                state["done"] = True
                finish()
                return
            QTimer.singleShot(250, poll)

        run_web_javascript(web, script, on_result)

    poll()
    loop.exec()
    timer.stop()
    if not state["done"]:
        raise TimeoutError(
            f"Timed out waiting for {label}; last value={state['last_value']!r}"
        )


def click_web_selector(web: Any, selector: str, label: str) -> None:
    result = eval_js(
        web,
        f"""
(() => {{
  const node = document.querySelector({selector!r});
  if (!node) {{
    return {{
      ok: false,
      reason: "missing-selector",
    }};
  }}
  const rect = node.getBoundingClientRect();
  return {{
    ok: true,
    text: node.textContent || "",
    tagName: node.tagName,
    width: rect.width,
    height: rect.height,
  }};
}})()
""",
    )
    if not result or not result.get("ok"):
        raise RuntimeError(f"{label}: selector not found")

    click_result = eval_js(
        web,
        f"""
(() => {{
  const node = document.querySelector({selector!r});
  if (!node) return {{ ok: false, reason: "missing-selector" }};
  node.scrollIntoView({{ block: "center", inline: "center" }});
  const rect = node.getBoundingClientRect();
  const centerX = Math.round(rect.left + rect.width / 2);
  const centerY = Math.round(rect.top + rect.height / 2);
  const eventInit = {{
    bubbles: true,
    cancelable: true,
    composed: true,
    view: window,
    clientX: centerX,
    clientY: centerY,
    button: 0,
  }};
  node.dispatchEvent(new MouseEvent("mousedown", eventInit));
  node.dispatchEvent(new MouseEvent("mouseup", eventInit));
  node.click();
  return {{
    ok: true,
    text: node.textContent || "",
    tagName: node.tagName,
  }};
}})()
""",
    )
    if not click_result or not click_result.get("ok"):
        raise RuntimeError(f"{label}: click script failed: {click_result}")


def wait_for_overlay_state(
    web: Any,
    *,
    label: str,
    overlay_selector: str,
    view_selector: str,
    description: str,
    timeout_ms: int = 10000,
) -> None:
    try:
        wait_for_condition(
            web,
            f"""
(() => {{
  const overlay = document.querySelector({overlay_selector!r});
  const view = document.querySelector({view_selector!r});
  return Boolean(
    overlay && view &&
    !overlay.classList.contains("hidden") &&
    !view.classList.contains("hidden")
  );
}})()
""",
            f"{label} {description}",
            timeout_ms=timeout_ms,
        )
    except TimeoutError as error:
        raise RuntimeError(f"{label}: {description} did not open (timeout)") from error


def maybe_pause_debug(
    *,
    report_path: Path,
    report: dict[str, Any],
    note_report: dict[str, Any] | None,
    debug: dict[str, Any],
    previewer: FixedCardPreviewer | None,
    label: str | None,
    pause_phase: str,
    artifacts_dir: Path,
    force: bool = False,
) -> None:
    if not debug["enabled"]:
        return
    if not force and pause_phase not in debug["pauseAt"]:
        return

    artifact = capture_debug_artifacts(
        previewer=previewer,
        artifacts_dir=artifacts_dir,
        label=label or "session",
        phase=pause_phase,
    )
    if note_report is not None:
        note_report.setdefault("debugArtifacts", []).append(artifact)

    debug["currentPause"] = {
        "label": label,
        "phase": pause_phase,
        "artifact": artifact,
    }
    sync_debug_report(report, debug)
    write_report(report_path, report)

    print(f"[lapis-e2e] paused at {pause_phase}")
    if debug["devtoolsUrl"]:
        print(f"[lapis-e2e] DevTools: {debug['devtoolsUrl']}")

    continue_path: Path = debug["continuePath"]
    clear_continue_file(continue_path)

    wait_for_continue_request(continue_path)

    print(f"[lapis-e2e] resuming from {pause_phase}")
    clear_continue_file(continue_path)
    debug["currentPause"] = None
    sync_debug_report(report, debug)
    write_report(report_path, report)


def capture_debug_artifacts(
    *,
    previewer: FixedCardPreviewer | None,
    artifacts_dir: Path,
    label: str,
    phase: str,
) -> dict[str, Any]:
    artifact_label = f"{label}-{sanitize_phase_name(phase)}"
    screenshot_path = artifacts_dir / f"{artifact_label}.png"
    dom_path = artifacts_dir / f"{artifact_label}.html"
    state_path = artifacts_dir / f"{artifact_label}.json"

    debug_state = {
        "phase": phase,
        "label": label,
        "overlayState": None,
        "probeState": None,
        "error": None,
    }
    if previewer is not None and previewer._web is not None:
        web = previewer._web
        web.grab().save(str(screenshot_path))
        try:
            dom = eval_js(web, "document.documentElement.outerHTML", timeout_ms=3000)
        except Exception as error:
            dom = f"Failed to capture DOM: {error}"
        dom_path.write_text(str(dom), encoding="utf-8")
        try:
            state = eval_js(
                web,
                """
(() => ({
  overlayState: {
    overlayVisible: !!document.querySelector("#lapis-lookup-overlay") &&
      !document.querySelector("#lapis-lookup-overlay").classList.contains("hidden"),
    kanjiOverlayVisible: !!document.querySelector("#kanji-popover-view") &&
      !document.querySelector("#kanji-popover-view").classList.contains("hidden"),
    wordOverlayVisible: !!document.querySelector("#word-popover-view") &&
      !document.querySelector("#word-popover-view").classList.contains("hidden"),
  },
  probeState: window.__lapisE2E || null,
}))()
""",
                timeout_ms=3000,
            )
            debug_state["overlayState"] = state.get("overlayState")
            debug_state["probeState"] = state.get("probeState")
        except Exception as error:
            debug_state["error"] = str(error)
    else:
        debug_state["error"] = "Preview webview unavailable."

    state_path.write_text(
        json.dumps(debug_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "phase": phase,
        "screenshotPath": str(screenshot_path) if screenshot_path.exists() else None,
        "domPath": str(dom_path) if dom_path.exists() else None,
        "statePath": str(state_path),
        "overlayState": debug_state["overlayState"],
        "probeState": debug_state["probeState"],
    }


def capture_failure_artifacts(previewer: FixedCardPreviewer, artifacts_dir: Path, label: str) -> None:
    web = previewer._web
    if web is None:
        return
    screenshot_path = artifacts_dir / f"{label}-failure.png"
    dom_path = artifacts_dir / f"{label}-failure.html"
    web.grab().save(str(screenshot_path))
    try:
        dom = eval_js(web, "document.documentElement.outerHTML")
    except Exception as error:
        dom = f"Failed to capture DOM: {error}"
    dom_path.write_text(str(dom), encoding="utf-8")


def wait_for_continue_request(path: Path) -> None:
    while not continue_requested(path):
        time.sleep(0.1)


def continue_requested(path: Path) -> bool:
    return path.exists()


def clear_continue_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
