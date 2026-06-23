import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    buildDictionaryStylesMap,
    buildTermDictionaryMap,
} from "../src/dictionaries.js";
import { buildLegacyLapisNoteInput } from "../src/lookup.js";
import type { DictionarySummary } from "../src/yomitan-types.js";

function createDictionarySummary(title: string): DictionarySummary {
    return {
        title,
        styles: ".term-glossary-list { color: red; }",
        counts: {
            terms: { total: 1 },
            termMeta: {},
            kanji: { total: 0 },
        },
    };
}

describe("legacy Lapis note input", () => {
    it("requests grouped Yomitan output for converted legacy notes", () => {
        const dictionaryInfo = [
            createDictionarySummary("Jitendex.org [2026-06-06]"),
            createDictionarySummary("JMdict"),
        ];

        const input = buildLegacyLapisNoteInput(
            "超人",
            dictionaryInfo,
            buildTermDictionaryMap(dictionaryInfo),
            buildDictionaryStylesMap(dictionaryInfo),
        );

        assert.equal(input.resultOutputMode, "group");
        assert.equal(
            input.dictionaryStylesMap?.get("Jitendex.org [2026-06-06]"),
            ".term-glossary-list { color: red; }",
        );
        assert.equal(
            input.cardFormat.fields.MainDefinition.value,
            "{single-glossary-jitendexorg-2026-06-06}{single-glossary-jmdict}",
        );
    });
});
