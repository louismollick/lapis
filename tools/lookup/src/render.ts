import type { KanjiDictionaryEntry } from "./yomitan-types.js";

export function renderFallbackKanjiHtml(entry: KanjiDictionaryEntry): string {
    const definitions = entry.definitions
        .map((definition) => `<li>${escapeHtml(definition)}</li>`)
        .join("");
    const readings = [
        ...entry.onyomi.map((reading) => `<span>${escapeHtml(reading)}</span>`),
        ...entry.kunyomi.map(
            (reading) => `<span>${escapeHtml(reading)}</span>`,
        ),
    ].join(" ");

    return `
        <div class="yomitan-glossary">
            ${readings ? `<div class="lapis-lookup-fallback-readings">${readings}</div>` : ""}
            ${definitions ? `<ul>${definitions}</ul>` : "<div>No kanji definitions available.</div>"}
        </div>
    `.trim();
}

function escapeHtml(value: string): string {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
