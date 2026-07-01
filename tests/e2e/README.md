# Lapis Lookup E2E

Run the container-backed harness with:

```bash
python3 /Users/mollicl/personal/lapis/tests/e2e/run_anki_lookup_e2e.py
```

Useful overrides:

- `--image <image>` or `LAPIS_ANKI_E2E_IMAGE=<image>` to use a local/runtime test image
- `--artifacts-dir <dir>` to keep reports, screenshots, and DOM dumps in a stable location
- `--keep-artifacts` to preserve the temporary artifact directory on success
- `--debug-webview` to expose the embedded Anki preview via Qt WebEngine DevTools
- `--debug-port <port>` to change the DevTools port from the default `9222`
- `--pause-at <phase[,phase,...]>` to pause at selected preview phases
- `--debug-keep-open` to pause before exit until resumed manually

Debug example:

```bash
python3 /Users/mollicl/personal/lapis/tests/e2e/run_anki_lookup_e2e.py \
  --debug-webview \
  --pause-at after-preview-render
```

When debug mode is enabled:

- open Chrome at `http://localhost:9222` unless `--debug-port` overrides it
- use the printed `touch <artifacts-dir>/debug-continue` command to resume from each pause
- inspect pause state in `report.json`

Supported pause phases:

- `after-preview-open`
- `after-preview-render`
- `after-targets-ready`
- `after-kanji-click`
- `after-kanji-overlay`
- `after-related-word-click`
- `after-word-overlay`

The checked-in fixture package is generated from current repo assets with:

```bash
python3 /Users/mollicl/personal/lapis/tests/e2e/generate_fixture.py
```
