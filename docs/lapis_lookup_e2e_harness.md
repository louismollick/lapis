# Lapis lookup E2E harness — preview failures (postmortem)

This document explains why the container-backed Anki E2E tests were stalling during the preview flow, and how the harness was fixed. The failures were in **harness/app interaction**, not in the GHCR Docker image or package version mismatches.

For how to run the tests, see [tests/e2e/README.md](../tests/e2e/README.md).

## Symptoms

- Tests hung at `preview-lapis:wait-for-targets` (or earlier preview phases) until the outer Docker timeout (often 180–300s).
- `report.json` showed backfill and media validation succeeding, but preview fields (`targetCount`, `clickedKanji`) stayed empty.
- Debug runs with `--pause-at after-preview-render` could succeed when given enough wall-clock time between pauses, which pointed to a timing/event-loop problem rather than missing lookup data.

## Root causes

### 1. Previewer rendered the question side instead of the answer

Anki’s `Previewer._render_scheduled()` resets `_state` to `"question"` whenever `_card_changed` is true. The harness set `_state = "answer"` and then called `render_card()` with `_card_changed = True`, which undid that and rendered the **front** template.

Lookup markup (kanji targets, store manifest, overlay) lives in the **back** template (`src/back.html`). With the question side showing, the wait condition for `.lapis-lookup-kanji-target` never became true.

### 2. Synchronous harness blocked Qt’s main event loop

`run_harness()` ran entirely on Anki’s main thread. After queuing `_showAnswer` in the preview webview, card JavaScript (`initialize()`, `initializeLookupOverlay()`, external `_lapis_lookup_store.js`) still needed the Qt event loop to run.

Blocking the main thread with nested `QEventLoop.exec()` or tight `processEvents()` loops either deadlocked with WebEngine or never let card scripts finish. Manual debug pauses worked because Anki kept processing events between steps.

### 3. Stale `_domDone` and premature “ready” checks

The preview webview sets `_domDone` when the reviewer shell loads. That flag stayed true after `_showAnswer` was queued, so early “wait for DOM” logic returned before the answer HTML and its scripts had actually run.

### 4. Anki exited before async preview work ran

An initial async-preview attempt scheduled follow-up work with `QTimer` but returned from `run_harness()` without marking the run as in-progress. The `finally` block called `finish_harness()` → `app.quit()`, so Anki exited before the deferred preview timers fired.

### 5. Audio playback in headless preview

`Previewer._render_scheduled()` calls `av_player.play_tags()` when a card has autoplay audio. In headless Docker that could block or stall the preview path. This was a secondary issue once the event-loop blocking was understood.

## Fixes

Changes are in `tests/e2e/lapis_anki_e2e/driver.py` and `tests/e2e/run_anki_lookup_e2e.py`.

### `FixedCardPreviewer`

- Opens directly on the **answer** side: custom `open()` skips the default question-first render.
- **`show_answer()`** clears `_card_changed`, resets `_last_state`, cancels debounce timers, and calls `_render_scheduled()` synchronously.
- **Skips preview audio** by temporarily no-op’ing `av_player.play_tags` during render.

### Async preview workflow

After fixture import, backfill, and media validation, preview work is deferred with `QTimer`:

1. `run_next_preview()` opens the previewer for the next note.
2. After **3.5 seconds** (allowing WebEngine to run card scripts), `continue_preview_note()` runs the interaction steps.
3. On completion, the next note is scheduled with `QTimer.singleShot(0, …)`.

`run_harness()` sets `report["phase"] = "preview-async"` before returning so `finish_harness()` does not quit Anki until all previews finish.

### JS polling

`eval_js` and `wait_for_condition` use `QTimer` with a nested `QEventLoop` and explicit timeouts, instead of spinning on `processEvents()`. This avoids WebEngine deadlocks while still delivering JavaScript callbacks.

### Runner cleanup

`run_anki_lookup_e2e.py` uses `Popen` with a Docker `--cidfile`, and force-removes the recorded container on timeout so hung runs do not leave orphaned Docker processes (which had caused “too many open files” on repeated failures).

## Verification

With these changes, the full E2E run completes in roughly **10–15 seconds** on the published `linux/amd64` image, with both fixture notes passing preview assertions (kanji targets, overlay interaction, dictionary body).

```text
Status: ok
lapis:  model=Lapis+Lookup  targets=2  clickedKanji=粒
legacy: model=Lapis+Lookup  targets=2  clickedKanji=銀
```
