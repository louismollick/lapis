from __future__ import annotations

import re


DEFAULT_DEBUG_PORT = 9222
DEBUG_CONTINUE_FILE_NAME = "debug-continue"
DEBUG_PHASES = (
    "after-preview-open",
    "after-preview-render",
    "after-targets-ready",
    "after-kanji-click",
    "after-kanji-overlay",
    "after-related-word-click",
    "after-word-overlay",
)


def parse_pause_at(raw: str | None) -> list[str]:
    if not raw:
        return []

    values: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        phase = item.strip()
        if not phase or phase in seen:
            continue
        if phase not in DEBUG_PHASES:
            raise ValueError(
                f"Unsupported debug pause phase: {phase}. "
                f"Expected one of: {', '.join(DEBUG_PHASES)}"
            )
        seen.add(phase)
        values.append(phase)
    return values


def devtools_url(port: int) -> str:
    return f"http://localhost:{port}"


def sanitize_phase_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "phase"
