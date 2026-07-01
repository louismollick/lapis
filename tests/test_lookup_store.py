from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib
import shutil
import sys
import tempfile
import types
import unittest


class LookupStoreTest(unittest.TestCase):
    def test_lookup_store_round_trips_sharded_media_js(self) -> None:
        install_aqt_stubs()
        lookup_store = importlib.import_module("anki_addon.lapis_lookup.lookup_store")
        with tempfile.TemporaryDirectory() as media_dir:
            col = FakeCollection(media_dir)
            store = lookup_store.merge_lookup_terms(
                None,
                {
                    "粒子": {
                        "term": "粒子",
                        "reading": "りゅうし",
                        "frequency": {"value": 1, "source": "JPDB"},
                        "entryHtml": "<div>particle</div>",
                    }
                },
            )

            warnings = lookup_store.write_lookup_store_to_media(col, store)

            self.assertEqual(warnings, [])
            self.assertEqual(lookup_store.read_lookup_store_from_media(col), store)
            self.assertTrue((Path(media_dir) / lookup_store.LOOKUP_STORE_MEDIA_NAME).exists())
            self.assertEqual(
                len(list(Path(media_dir).glob("_lapis_lookup_store_*.js"))),
                lookup_store.LOOKUP_STORE_SHARD_COUNT,
            )


class BackfillApplicationTest(unittest.TestCase):
    def test_init_registers_hooks_once(self) -> None:
        addon = load_addon()
        addon.gui_hooks.browser_menus_did_init.clear()
        addon.gui_hooks.add_cards_did_add_note.clear()
        addon.anki_hooks.note_will_be_added.clear()

        addon.init()
        addon.init()

        self.assertEqual(addon.gui_hooks.browser_menus_did_init, [addon.add_browser_menu])
        self.assertEqual(addon.gui_hooks.add_cards_did_add_note, [addon.on_add_cards_did_add_note])
        self.assertEqual(addon.anki_hooks.note_will_be_added, [addon.on_note_will_be_added])

    def test_mixed_legacy_and_lapis_backfill_use_one_canonical_lookup_model(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        legacy_model = col.models.add_model(
            {
                "id": 1,
                "name": "Legacy Mining",
                "flds": [{"name": "Front"}, {"name": "Back"}],
                "tmpls": [{"name": "Card 1", "afmt": "{{Front}}", "qfmt": "{{Front}}"}],
                "css": "",
                "sortf": 0,
            }
        )
        lapis_model = col.models.add_model(build_lapis_model(2, "Lapis"))
        col.notes[101] = FakeNote(101, legacy_model["id"], col, {"Front": "粒子"})
        col.notes[102] = FakeNote(102, lapis_model["id"], col, {"Expression": "銀"})

        summary = addon.apply_pending_lookup_items(
            col,
            [
                {
                    "noteId": 101,
                    "mode": addon.LEGACY_CONVERT_MODE,
                    "status": "ok",
                    "expression": "粒子",
                    "generatedFields": {"Expression": "粒子", "Glossary": "<div>particle</div>"},
                    "payload": {"version": 2, "expression": "粒子", "kanji": []},
                },
                {
                    "noteId": 102,
                    "mode": addon.LOOKUP_ONLY_MODE,
                    "status": "ok",
                    "expression": "銀",
                    "payload": {"version": 2, "expression": "銀", "kanji": []},
                },
            ],
            addon.BackfillState(),
        )

        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.invariant_violations, [])
        self.assertEqual(col.notes[101].note_type()["name"], addon.CANONICAL_LAPIS_MODEL_NAME)
        self.assertEqual(col.notes[102].note_type()["name"], addon.CANONICAL_LAPIS_MODEL_NAME)
        self.assertEqual(col.notes[101].mid, col.notes[102].mid)
        self.assertTrue(col.notes[101][addon.LOOKUP_FIELD_NAME])
        self.assertTrue(col.notes[102][addon.LOOKUP_FIELD_NAME])

    def test_canonical_sync_does_not_reorder_existing_fields(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        model = col.models.add_model(
            {
                "id": 1,
                "name": addon.CANONICAL_LAPIS_MODEL_NAME,
                "flds": [
                    {"name": "Expression"},
                    {"name": "Frequency"},
                    {"name": "MiscInfo"},
                    {"name": "FreqSort"},
                ],
                "tmpls": [{"name": "Mining", "afmt": "", "qfmt": ""}],
                "css": "",
                "sortf": 0,
            }
        )
        col.notes[101] = FakeNote(
            101,
            model["id"],
            col,
            {"Expression": "甲冑", "MiscInfo": "Dorohedoro 13", "FreqSort": "12345"},
        )

        changed = addon.sync_canonical_lookup_model(col, model)

        self.assertTrue(changed)
        field_names = [field["name"] for field in model["flds"]]
        self.assertEqual(field_names[:4], ["Expression", "Frequency", "MiscInfo", "FreqSort"])
        self.assertEqual(col.notes[101]["MiscInfo"], "Dorohedoro 13")
        self.assertEqual(col.notes[101]["FreqSort"], "12345")

    def test_missing_payload_does_not_convert_note(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        base_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, base_model["id"], col, {"Expression": "粒子"})

        summary = addon.apply_backfill_item(
            col,
            {
                "noteId": 101,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": "粒子",
            },
            addon.BackfillState(),
        )

        self.assertEqual(summary.processed, 0)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(col.notes[101].mid, base_model["id"])
        self.assertFalse(addon.note_has_field(col.notes[101], addon.LOOKUP_FIELD_NAME))

    def test_valid_payload_converts_and_writes_lookup_data(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        base_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, base_model["id"], col, {"Expression": "粒子"})

        summary = addon.apply_backfill_item(
            col,
            {
                "noteId": 101,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": "粒子",
                "payload": {"version": 2, "expression": "粒子", "kanji": []},
            },
            addon.BackfillState(),
        )

        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.failed, 0)
        self.assertNotEqual(col.notes[101].mid, base_model["id"])
        self.assertTrue(addon.note_has_field(col.notes[101], addon.LOOKUP_FIELD_NAME))
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])
        self.assertTrue(addon.is_lookup_ready_model(col.models.get(col.notes[101].mid)))

    def test_valid_payload_repairs_broken_lookup_template(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        lookup_model = col.models.add_model(build_lapis_model(1, addon.CANONICAL_LAPIS_MODEL_NAME))
        addon.ensure_lookup_field(col, lookup_model)
        addon.apply_lookup_assets(lookup_model)
        lookup_model["tmpls"][0]["afmt"] = lookup_model["tmpls"][0]["afmt"].replace(
            "{{text:KanjiLookupData}}",
            "",
        )
        col.models.update_dict(lookup_model)
        col.notes[101] = FakeNote(
            101,
            lookup_model["id"],
            col,
            {"Expression": "粒子", addon.LOOKUP_FIELD_NAME: ""},
        )

        summary = addon.apply_backfill_item(
            col,
            {
                "noteId": 101,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": "粒子",
                "payload": {"version": 2, "expression": "粒子", "kanji": []},
            },
            addon.BackfillState(),
        )

        repaired_model = col.models.get(col.notes[101].mid)
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(col.notes[101].mid, lookup_model["id"])
        self.assertTrue(addon.is_lookup_ready_model(repaired_model))
        self.assertIn(
            "{{text:KanjiLookupData}}",
            repaired_model["tmpls"][0]["afmt"],
        )
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])

    def test_broken_canonical_lookup_model_is_repaired_in_place(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        lookup_model = col.models.add_model(build_lapis_model(1, addon.CANONICAL_LAPIS_MODEL_NAME))
        addon.ensure_lookup_field(col, lookup_model)
        addon.apply_lookup_assets(lookup_model)
        lookup_model["tmpls"][0]["afmt"] = lookup_model["tmpls"][0]["afmt"].replace(
            "{{text:KanjiLookupData}}",
            "",
        )
        col.models.update_dict(lookup_model)
        target_model = addon.ensure_canonical_lookup_model(col)

        self.assertEqual(target_model["id"], lookup_model["id"])
        self.assertTrue(addon.is_lookup_ready_model(target_model))

    def test_stale_canonical_lookup_model_is_synced_before_write(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        lookup_model = addon.create_canonical_lookup_model(col)
        lookup_model["tmpls"][0]["qfmt"] = "{{Expression}} stale"
        col.models.update_dict(lookup_model)
        col.notes[101] = FakeNote(
            101,
            lookup_model["id"],
            col,
            {"Expression": "粒子", addon.LOOKUP_FIELD_NAME: ""},
        )

        summary = addon.apply_backfill_item(
            col,
            {
                "noteId": 101,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": "粒子",
                "payload": {"version": 2, "expression": "粒子", "kanji": []},
            },
            addon.BackfillState(),
        )

        synced_model = col.models.get(col.notes[101].mid)
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(synced_model["tmpls"][0]["qfmt"], addon.FRONT_TEMPLATE)
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])

    def test_obsolete_legacy_lookup_model_migrates_to_canonical_model(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        obsolete_model = col.models.add_model(build_lapis_model(1, "Lapis Legacy+Lookup"))
        addon.ensure_lookup_field(col, obsolete_model)
        addon.apply_lookup_assets(obsolete_model)
        col.notes[101] = FakeNote(
            101,
            obsolete_model["id"],
            col,
            {"Expression": "粒子", addon.LOOKUP_FIELD_NAME: ""},
        )

        summary = addon.apply_backfill_item(
            col,
            {
                "noteId": 101,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": "粒子",
                "payload": {"version": 2, "expression": "粒子", "kanji": []},
            },
            addon.BackfillState(),
        )

        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.failed, 0)
        self.assertNotEqual(col.notes[101].mid, obsolete_model["id"])
        self.assertEqual(col.notes[101].note_type()["name"], addon.CANONICAL_LAPIS_MODEL_NAME)
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])

    def test_processed_blank_note_becomes_invariant_failure(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        lookup_model = addon.create_canonical_lookup_model(col)
        col.notes[101] = FakeNote(
            101,
            lookup_model["id"],
            col,
            {"Expression": "超人", addon.LOOKUP_FIELD_NAME: ""},
        )

        violations = addon.find_lookup_payload_violations(col, {101})

        self.assertEqual(
            violations,
            ["Note 101 (超人): lookup-enabled note has blank KanjiLookupData"],
        )

    def test_pending_backfill_reports_failures_loudly(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        base_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, base_model["id"], col, {"Expression": "粒子"})

        summary = addon.apply_pending_lookup_items(
            col,
            [{"noteId": 101, "mode": addon.LOOKUP_ONLY_MODE, "status": "ok", "expression": "粒子"}],
            addon.BackfillState(),
        )
        report = addon.format_backfill_failure_report(summary)

        self.assertIn("Lapis lookup backfill finished with failures.", report)
        self.assertIn("Failed: 1", report)
        self.assertIn("Note 101 (粒子): lookup payload missing", report)

    def test_manual_setup_uses_shared_lookup_job(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        legacy_model = col.models.add_model(
            {
                "id": 1,
                "name": "Legacy Mining",
                "flds": [{"name": "Front"}, {"name": "Back"}],
                "tmpls": [{"name": "Card 1", "afmt": "{{Front}}", "qfmt": "{{Front}}"}],
                "css": "",
                "sortf": 0,
            }
        )
        lapis_model = col.models.add_model(build_lapis_model(2, "Lapis"))
        col.notes[101] = FakeNote(101, legacy_model["id"], col, {"Front": "粒子"})
        col.notes[102] = FakeNote(102, lapis_model["id"], col, {"Expression": "銀"})
        calls: list[dict] = []

        def fake_start_lookup_job(**kwargs) -> None:
            calls.append(kwargs)

        original_start_lookup_job = addon.start_lookup_job
        addon.start_lookup_job = fake_start_lookup_job
        try:
            browser = FakeBrowser([101, 102])
            addon.setup_and_backfill_selected_notes(browser)
        finally:
            addon.start_lookup_job = original_start_lookup_job

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["lookup_items"],
            [
                {"noteId": 101, "mode": addon.LEGACY_CONVERT_MODE, "expression": "粒子"},
                {"noteId": 102, "mode": addon.LOOKUP_ONLY_MODE, "expression": "銀"},
            ],
        )

class AutoBackfillTest(unittest.TestCase):
    def test_collection_hook_drains_after_note_gets_id(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lapis_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        note = FakeNote(0, lapis_model["id"], col, {"Expression": "超人"})
        calls: list[int] = []

        original_enqueue = addon.enqueue_auto_backfill_note_id
        addon.enqueue_auto_backfill_note_id = lambda _col, note_id: calls.append(note_id)
        try:
            addon.on_note_will_be_added(col, note, None)
            self.assertEqual(calls, [])
            note.id = 101
            addon.drain_pending_added_notes()
        finally:
            addon.enqueue_auto_backfill_note_id = original_enqueue

        self.assertEqual(calls, [101])
        self.assertEqual(addon.PENDING_ADDED_NOTES, [])

    def test_auto_backfill_eligibility_rules(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        legacy_model = col.models.add_model(
            {
                "id": 1,
                "name": "Legacy Mining",
                "flds": [{"name": "Front"}, {"name": "Back"}],
                "tmpls": [{"name": "Card 1", "afmt": "{{Front}}", "qfmt": "{{Front}}"}],
                "css": "",
                "sortf": 0,
            }
        )
        lapis_model = col.models.add_model(build_lapis_model(2, "Lapis"))
        lookup_model = addon.create_canonical_lookup_model(col)
        col.notes[101] = FakeNote(101, legacy_model["id"], col, {"Front": "粒子"})
        col.notes[102] = FakeNote(102, lapis_model["id"], col, {"Expression": ""})
        col.notes[103] = FakeNote(103, lookup_model["id"], col, {"Expression": "銀", addon.LOOKUP_FIELD_NAME: '{"version":2}'})
        col.notes[104] = FakeNote(104, lapis_model["id"], col, {"Expression": "超人"})

        self.assertFalse(addon.is_auto_backfill_note_id_eligible(col, 101))
        self.assertFalse(addon.is_auto_backfill_note_id_eligible(col, 102))
        self.assertFalse(addon.is_auto_backfill_note_id_eligible(col, 103))
        self.assertTrue(addon.is_auto_backfill_note_id_eligible(col, 104))

    def test_first_auto_backfill_note_starts_job(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lapis_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, lapis_model["id"], col, {"Expression": "超人"})
        calls: list[dict] = []

        def fake_start_lookup_job(**kwargs) -> None:
            calls.append(kwargs)

        original_start_lookup_job = addon.start_lookup_job
        addon.start_lookup_job = fake_start_lookup_job
        try:
            addon.enqueue_auto_backfill_note_id(col, 101)
        finally:
            addon.start_lookup_job = original_start_lookup_job

        self.assertTrue(addon.AUTO_BACKFILL_QUEUE.running)
        self.assertEqual(addon.AUTO_BACKFILL_QUEUE.pending_note_ids, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["lookup_items"], [{"noteId": 101, "mode": addon.LOOKUP_ONLY_MODE, "expression": "超人"}])

    def test_auto_backfill_queues_note_added_while_run_active(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lapis_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, lapis_model["id"], col, {"Expression": "超人"})
        col.notes[102] = FakeNote(102, lapis_model["id"], col, {"Expression": "粒子"})
        calls: list[dict] = []

        def fake_start_lookup_job(**kwargs) -> None:
            calls.append(kwargs)

        original_start_lookup_job = addon.start_lookup_job
        addon.start_lookup_job = fake_start_lookup_job
        try:
            addon.enqueue_auto_backfill_note_id(col, 101)
            addon.enqueue_auto_backfill_note_id(col, 102)
        finally:
            addon.start_lookup_job = original_start_lookup_job

        self.assertEqual(len(calls), 1)
        self.assertEqual(addon.AUTO_BACKFILL_QUEUE.pending_note_ids, [102])

    def test_auto_backfill_processes_followup_batch_after_success(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lapis_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, lapis_model["id"], col, {"Expression": "超人"})
        col.notes[102] = FakeNote(102, lapis_model["id"], col, {"Expression": "粒子"})
        col.notes[103] = FakeNote(103, lapis_model["id"], col, {"Expression": "銀"})
        calls: list[dict] = []

        def fake_start_lookup_job(**kwargs) -> None:
            calls.append(kwargs)

        original_start_lookup_job = addon.start_lookup_job
        original_show_warning = addon.showWarning
        addon.start_lookup_job = fake_start_lookup_job
        addon.showWarning = lambda *_args, **_kwargs: None
        try:
            addon.enqueue_auto_backfill_note_id(col, 101)
            addon.enqueue_auto_backfill_note_id(col, 102)
            addon.enqueue_auto_backfill_note_id(col, 103)
            calls[0]["success"](lookup_results(addon, 101, "超人"))
        finally:
            addon.start_lookup_job = original_start_lookup_job
            addon.showWarning = original_show_warning

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1]["lookup_items"],
            [
                {"noteId": 102, "mode": addon.LOOKUP_ONLY_MODE, "expression": "粒子"},
                {"noteId": 103, "mode": addon.LOOKUP_ONLY_MODE, "expression": "銀"},
            ],
        )
        self.assertTrue(addon.AUTO_BACKFILL_QUEUE.running)

    def test_auto_backfill_converts_base_lapis_note_and_writes_lookup_data(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lapis_model = col.models.add_model(build_lapis_model(1, "Lapis"))
        col.notes[101] = FakeNote(101, lapis_model["id"], col, {"Expression": "粒子"})

        def fake_start_lookup_job(**kwargs) -> None:
            kwargs["success"](lookup_results(addon, 101, "粒子"))

        original_start_lookup_job = addon.start_lookup_job
        original_show_warning = addon.showWarning
        addon.start_lookup_job = fake_start_lookup_job
        addon.showWarning = lambda *_args, **_kwargs: None
        try:
            addon.on_add_cards_did_add_note(col.notes[101])
        finally:
            addon.start_lookup_job = original_start_lookup_job
            addon.showWarning = original_show_warning

        self.assertFalse(addon.AUTO_BACKFILL_QUEUE.running)
        self.assertEqual(addon.AUTO_BACKFILL_QUEUE.pending_note_ids, [])
        self.assertNotEqual(col.notes[101].mid, lapis_model["id"])
        self.assertTrue(addon.note_has_field(col.notes[101], addon.LOOKUP_FIELD_NAME))
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])

    def test_auto_backfill_repairs_stale_canonical_model_before_write(self) -> None:
        addon = load_addon()
        col = FakeCollection()
        addon.mw.col = col
        addon.reset_auto_backfill_queue()
        lookup_model = addon.create_canonical_lookup_model(col)
        lookup_model["tmpls"][0]["qfmt"] = "{{Expression}} stale"
        col.models.update_dict(lookup_model)
        col.notes[101] = FakeNote(
            101,
            lookup_model["id"],
            col,
            {"Expression": "粒子", addon.LOOKUP_FIELD_NAME: ""},
        )

        def fake_start_lookup_job(**kwargs) -> None:
            kwargs["success"](lookup_results(addon, 101, "粒子"))

        original_start_lookup_job = addon.start_lookup_job
        original_show_warning = addon.showWarning
        addon.start_lookup_job = fake_start_lookup_job
        addon.showWarning = lambda *_args, **_kwargs: None
        try:
            addon.on_add_cards_did_add_note(col.notes[101])
        finally:
            addon.start_lookup_job = original_start_lookup_job
            addon.showWarning = original_show_warning

        synced_model = col.models.get(col.notes[101].mid)
        self.assertEqual(synced_model["tmpls"][0]["qfmt"], addon.FRONT_TEMPLATE)
        self.assertIn('"version":2', col.notes[101][addon.LOOKUP_FIELD_NAME])


class FakeCollection:
    def __init__(self, media_dir: str | None = None) -> None:
        self.models = FakeModels(self)
        self.notes: dict[int, FakeNote] = {}
        self.db = FakeDb(self)
        self.media = FakeMedia(media_dir) if media_dir else None

    def get_note(self, note_id: int) -> "FakeNote":
        return self.notes[int(note_id)].clone()

    def update_note(self, note: "FakeNote", skip_undo_entry: bool = True) -> None:
        self.notes[note.id] = note.clone()

    def transact(self, op) -> object:
        snapshot = deepcopy((self.models.models, self.notes, self.models.next_id))
        try:
            return op()
        except Exception:
            self.models.models, self.notes, self.models.next_id = snapshot
            raise


class FakeMedia:
    def __init__(self, media_dir: str) -> None:
        self._media_dir = media_dir

    def dir(self) -> str:
        return self._media_dir


class FakeDb:
    def __init__(self, col: FakeCollection) -> None:
        self.col = col

    def scalar(self, _query: str, note_id: int) -> str | None:
        note = self.col.notes.get(int(note_id))
        if note is None:
            return None
        return "\x1f".join(note.fields)


class FakeModels:
    def __init__(self, col: FakeCollection) -> None:
        self.col = col
        self.models: dict[int, dict] = {}
        self.next_id = 1

    def add_model(self, model: dict) -> dict:
        self.models[model["id"]] = model
        self.next_id = max(self.next_id, model["id"] + 1)
        return model

    def all_names_and_ids(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(id=model_id, name=model["name"])
            for model_id, model in sorted(self.models.items())
        ]

    def get(self, model_id: int) -> dict:
        return self.models[int(model_id)]

    def copy(self, model: dict, add: bool = False) -> dict:
        copied = deepcopy(model)
        copied["id"] = self.next_id
        return copied

    def add(self, model: dict) -> None:
        if model["id"] in self.models:
            model["id"] = self.next_id
        self.models[model["id"]] = model
        self.next_id = max(self.next_id, model["id"] + 1)

    def update_dict(self, model: dict, skip_checks: bool = True) -> None:
        self.models[model["id"]] = model

    def new_field(self, name: str) -> dict:
        return {"name": name}

    def add_field(self, model: dict, field: dict) -> None:
        model["flds"].append(field)

    def new(self, name: str) -> dict:
        return {"id": self.next_id, "name": name, "flds": [], "tmpls": [], "css": ""}

    def new_template(self, name: str) -> dict:
        return {"name": name, "qfmt": "", "afmt": ""}

    def add_template(self, model: dict, template: dict) -> None:
        model["tmpls"].append(template)

    def change(
        self,
        old_model: dict,
        note_ids: list[int],
        new_model: dict,
        field_map: dict[int, int],
        template_map: dict[int, int],
    ) -> None:
        for note_id in note_ids:
            note = self.col.notes[int(note_id)]
            old_fields = note.fields
            new_values = [""] * len(new_model["flds"])
            for old_index, new_index in field_map.items():
                if old_index < len(old_fields) and new_index < len(new_values):
                    new_values[new_index] = old_fields[old_index]
            note.mid = new_model["id"]
            note.raw_fields = new_values


class FakeNote:
    def __init__(self, note_id: int, mid: int, col: FakeCollection, values: dict[str, str] | None = None) -> None:
        self.id = note_id
        self.mid = mid
        self.col = col
        field_names = [field["name"] for field in self.note_type()["flds"]]
        values = values or {}
        self.raw_fields = [values.get(name, "") for name in field_names]

    def clone(self) -> "FakeNote":
        cloned = object.__new__(FakeNote)
        cloned.id = self.id
        cloned.mid = self.mid
        cloned.col = self.col
        cloned.raw_fields = list(self.raw_fields)
        return cloned

    def note_type(self) -> dict:
        return self.col.models.get(self.mid)

    @property
    def fields(self) -> list[str]:
        return list(self.raw_fields)

    def __getitem__(self, field_name: str) -> str:
        index = self.field_index(field_name)
        return self.raw_fields[index] if index < len(self.raw_fields) else ""

    def __setitem__(self, field_name: str, value: str) -> None:
        index = self.field_index(field_name)
        while len(self.raw_fields) <= index:
            self.raw_fields.append("")
        self.raw_fields[index] = value

    def field_index(self, field_name: str) -> int:
        for index, field in enumerate(self.note_type()["flds"]):
            if field["name"] == field_name:
                return index
        raise KeyError(field_name)


def build_lapis_model(model_id: int, name: str) -> dict:
    return {
        "id": model_id,
        "name": name,
        "flds": [
            {"name": "Expression"},
            {"name": "ExpressionFurigana"},
            {"name": "MainDefinition"},
            {"name": "Glossary"},
            {"name": "Sentence"},
            {"name": "FreqSort"},
        ],
        "tmpls": [{"name": "Mining", "afmt": '<div class="vocab">{{Expression}}</div>', "qfmt": "{{Expression}}"}],
        "css": "",
        "sortf": 0,
    }


def lookup_results(addon, note_id: int, expression: str) -> dict:
    return {
        "results": [
            {
                "noteId": note_id,
                "mode": addon.LOOKUP_ONLY_MODE,
                "status": "ok",
                "expression": expression,
                "payload": {"version": 2, "expression": expression, "kanji": []},
            }
        ]
    }


class FakeBrowser:
    def __init__(self, note_ids: list[int]) -> None:
        self._note_ids = note_ids

    def selected_notes(self) -> list[int]:
        return list(self._note_ids)

    def search(self) -> None:
        return None


def load_addon():
    install_aqt_stubs()
    addon = importlib.import_module("anki_addon.lapis_lookup.addon")
    addon.reset_auto_backfill_queue()
    flush_qt_timers()
    return addon


def install_aqt_stubs() -> None:
    if "aqt" in sys.modules:
        return

    aqt = types.ModuleType("aqt")
    aqt.gui_hooks = SimpleNamespace(browser_menus_did_init=[], add_cards_did_add_note=[])
    aqt.mw = SimpleNamespace(
        taskman=None,
        addonManager=SimpleNamespace(getConfig=lambda _name: {}),
    )
    sys.modules["aqt"] = aqt

    browser = types.ModuleType("aqt.browser")
    browser.Browser = object
    sys.modules["aqt.browser"] = browser

    operations = types.ModuleType("aqt.operations")
    operations.QueryOp = object
    sys.modules["aqt.operations"] = operations

    qt = types.ModuleType("aqt.qt")
    qt.QAction = object
    qt.QMenu = object
    qt.QTimer = FakeQTimer
    qt.qconnect = lambda *_args: None
    sys.modules["aqt.qt"] = qt

    utils = types.ModuleType("aqt.utils")
    utils.showInfo = lambda *_args, **_kwargs: None
    utils.showWarning = lambda *_args, **_kwargs: None
    utils.tooltip = lambda *_args, **_kwargs: None
    sys.modules["aqt.utils"] = utils

    anki = types.ModuleType("anki")
    anki_hooks = types.ModuleType("anki.hooks")
    anki_hooks.note_will_be_added = []
    anki.hooks = anki_hooks
    sys.modules["anki"] = anki
    sys.modules["anki.hooks"] = anki_hooks


class FakeQTimer:
    pending: list[tuple[int, object]] = []

    @classmethod
    def singleShot(cls, delay_ms: int, callback) -> None:
        cls.pending.append((delay_ms, callback))


def flush_qt_timers() -> None:
    pending = list(FakeQTimer.pending)
    FakeQTimer.pending.clear()
    for _delay, callback in pending:
        callback()


if __name__ == "__main__":
    unittest.main()
