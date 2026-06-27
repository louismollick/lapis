from __future__ import annotations

import base64
import json
import re
import zlib
from pathlib import Path
from typing import Any


LOOKUP_STORE_MEDIA_NAME = "_lapis_lookup_store.js"
LOOKUP_STORE_SHARD_PREFIX = "_lapis_lookup_store_"
LOOKUP_STORE_SHARD_SUFFIX = ".js"
LOOKUP_STORE_SHARD_COUNT = 64
LOOKUP_STORE_ENCODING = "zlib+base64-json"
LOOKUP_STORE_VERSION = 2


def empty_lookup_store() -> dict[str, Any]:
    return {"version": LOOKUP_STORE_VERSION, "terms": {}}


def merge_lookup_terms(
    store: dict[str, Any] | None,
    shared_terms: dict[str, Any],
) -> dict[str, Any]:
    merged = empty_lookup_store()
    if store and isinstance(store.get("terms"), dict):
        merged["terms"].update(store["terms"])
    merged["terms"].update(shared_terms)
    return merged


def stable_lookup_hash(value: str) -> int:
    result = 2166136261
    for character in value:
        result ^= ord(character)
        result = (result * 16777619) & 0xFFFFFFFF
    return result


def lookup_term_shard(term: str) -> int:
    return stable_lookup_hash(term) % LOOKUP_STORE_SHARD_COUNT


def lookup_store_shard_media_name(
    shard_index: int,
    prefix: str = LOOKUP_STORE_SHARD_PREFIX,
    suffix: str = LOOKUP_STORE_SHARD_SUFFIX,
) -> str:
    return f"{prefix}{shard_index:02d}{suffix}"


def compress_lookup_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(zlib.compress(encoded, level=9)).decode("ascii")


def decompress_lookup_payload(payload: str) -> dict[str, Any]:
    decoded = base64.b64decode(payload, validate=True)
    return json.loads(zlib.decompress(decoded).decode("utf-8"))


def render_lookup_store_install_js(envelope: dict[str, Any]) -> str:
    return f"window.__lapisLookupInstallStore({json.dumps(envelope, separators=(',', ':'))});\n"


def render_lookup_store_manifest_js() -> str:
    envelope = {
        "version": LOOKUP_STORE_VERSION,
        "type": "manifest",
        "encoding": LOOKUP_STORE_ENCODING,
        "shardCount": LOOKUP_STORE_SHARD_COUNT,
        "shardPrefix": LOOKUP_STORE_SHARD_PREFIX,
        "shardSuffix": LOOKUP_STORE_SHARD_SUFFIX,
    }
    return render_lookup_store_install_js(envelope)


def render_lookup_store_shard_js(shard_index: int, terms: dict[str, Any]) -> str:
    envelope = {
        "version": LOOKUP_STORE_VERSION,
        "type": "shard",
        "encoding": LOOKUP_STORE_ENCODING,
        "shard": shard_index,
        "payload": compress_lookup_payload(
            {"version": LOOKUP_STORE_VERSION, "terms": terms}
        ),
    }
    return render_lookup_store_install_js(envelope)


def build_lookup_store_shards(store: dict[str, Any]) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = [{} for _ in range(LOOKUP_STORE_SHARD_COUNT)]
    terms = store.get("terms") if isinstance(store, dict) else None
    if not isinstance(terms, dict):
        return shards
    for term, payload in terms.items():
        shards[lookup_term_shard(str(term))][term] = payload
    return shards


def parse_lookup_store_envelope(source: str) -> dict[str, Any] | None:
    match = re.fullmatch(
        r"\s*window\.__lapisLookupInstallStore\((.*)\);\s*",
        source,
        flags=re.S,
    )
    if not match:
        return None
    envelope = json.loads(match.group(1))
    return envelope if isinstance(envelope, dict) else None


def parse_lookup_store_js(source: str) -> dict[str, Any]:
    envelope = parse_lookup_store_envelope(source)
    if not envelope:
        return empty_lookup_store()

    if envelope.get("encoding") != LOOKUP_STORE_ENCODING:
        return empty_lookup_store()
    if "payload" not in envelope:
        return empty_lookup_store()

    store = decompress_lookup_payload(envelope.get("payload", ""))
    if not isinstance(store, dict) or not isinstance(store.get("terms"), dict):
        return empty_lookup_store()
    return {"version": LOOKUP_STORE_VERSION, "terms": store["terms"]}


def lookup_store_media_path(col: Any) -> Path | None:
    media = getattr(col, "media", None)
    media_dir = getattr(media, "dir", None)
    if not callable(media_dir):
        return None
    return Path(media_dir()) / LOOKUP_STORE_MEDIA_NAME


def read_lookup_store_from_media(col: Any) -> dict[str, Any]:
    path = lookup_store_media_path(col)
    if path is None or not path.exists():
        return empty_lookup_store()
    try:
        source = path.read_text(encoding="utf-8")
        envelope = parse_lookup_store_envelope(source)
        if not envelope or envelope.get("type") != "manifest":
            return empty_lookup_store()

        merged = empty_lookup_store()
        shard_count = int(envelope.get("shardCount", LOOKUP_STORE_SHARD_COUNT))
        shard_prefix = str(envelope.get("shardPrefix", LOOKUP_STORE_SHARD_PREFIX))
        shard_suffix = str(envelope.get("shardSuffix", LOOKUP_STORE_SHARD_SUFFIX))
        for shard_index in range(shard_count):
            shard_path = path.parent / lookup_store_shard_media_name(
                shard_index,
                shard_prefix,
                shard_suffix,
            )
            if not shard_path.exists():
                continue
            shard_store = parse_lookup_store_js(shard_path.read_text(encoding="utf-8"))
            merged["terms"].update(shard_store["terms"])
        return merged
    except Exception:
        return empty_lookup_store()


def write_lookup_store_to_media(col: Any, store: dict[str, Any]) -> list[str]:
    path = lookup_store_media_path(col)
    if path is None:
        return ["Lookup store media could not be written: media directory unavailable."]

    path.write_text(render_lookup_store_manifest_js(), encoding="utf-8")
    for shard_index, terms in enumerate(build_lookup_store_shards(store)):
        shard_path = path.parent / lookup_store_shard_media_name(shard_index)
        shard_path.write_text(
            render_lookup_store_shard_js(shard_index, terms),
            encoding="utf-8",
        )
    return []
