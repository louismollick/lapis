import assert from "node:assert/strict";
import fs from "node:fs";
import { describe, it } from "node:test";

import {
    buildDictionaryStylesMap,
    buildTermDictionaryMap,
} from "../src/dictionaries.js";
import { parseKanjiRelatedData } from "../src/kanji-provider.js";
import {
    buildLegacyLapisNoteInput,
    buildLookupResult,
    buildProgressItem,
    buildRelatedWordDefinitionInput,
    createLookupCache,
    renderRelatedWordEntryHtml,
} from "../src/lookup.js";
import type {
    DictionarySummary,
    TermDictionaryEntry,
    YomitanCoreLike,
} from "../src/yomitan-types.js";

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
        assert.equal(input.cardFormat.fields.MainDefinition.value, "");
    });
});

describe("streamed lookup helpers", () => {
    it("emits progress frames with note identity and chunk-local position", () => {
        assert.deepEqual(
            buildProgressItem(
                {
                    noteId: 123,
                    mode: "lookupOnly",
                    expression: "粒子",
                },
                5,
                100,
            ),
            {
                type: "progress",
                completed: 5,
                total: 100,
                noteId: 123,
                expression: "粒子",
            },
        );
    });

    it("reuses converted fields for repeated expressions in one runtime", async () => {
        let buildAnkiNoteCalls = 0;
        const dictionaryInfo = [
            createDictionarySummary("Jitendex.org [2026-06-06]"),
        ];
        const runtime = {
            core: {
                buildAnkiNoteFromTerm: async () => {
                    buildAnkiNoteCalls += 1;
                    return {
                        status: "ok",
                        fields: {
                            Expression: "かな",
                        },
                        errors: [],
                    };
                },
            },
            dictionaryInfo,
            dictionaryStylesMap: buildDictionaryStylesMap(dictionaryInfo),
            termDictionaryMap: buildTermDictionaryMap(dictionaryInfo),
            kanjiDictionaryMap: new Map(),
            cache: createLookupCache(),
        };
        const options = {
            maxWordsPerKanji: 12,
            definitionDictionaryNames: ["Jitendex"],
            frequencyDictionaryNames: ["JPDB"],
        };

        const first = await buildLookupResult(
            {
                noteId: 1,
                mode: "convertLegacy",
                expression: "かな",
            },
            runtime as never,
            options,
        );
        const second = await buildLookupResult(
            {
                noteId: 2,
                mode: "convertLegacy",
                expression: "かな",
            },
            runtime as never,
            options,
        );

        assert.equal(buildAnkiNoteCalls, 1);
        assert.equal(first.noteId, 1);
        assert.equal(first.payload?.version, 2);
        assert.deepEqual(first.payload?.kanji, []);
        assert.deepEqual(first.sharedTerms, {});
        assert.equal(second.noteId, 2);
        assert.equal(second.generatedFields?.Expression, "かな");
    });
});

describe("related word definition rendering", () => {
    it("separates JPDB kanji decomposition data from related words", () => {
        const parsed = parseKanjiRelatedData([
            "何故",
            "",
            "漢字分解:",
            "亻 可",
        ]);

        assert.deepEqual(parsed, {
            relatedWords: ["何故"],
            components: ["亻 可"],
        });
    });

    it("requests grouped Yomitan output for selected related-word entries", () => {
        const dictionaryInfo = [
            createDictionarySummary("Jitendex.org [2026-06-06]"),
        ];
        const input = buildRelatedWordDefinitionInput(
            createTermEntry(),
            "超える",
            "Jitendex.org [2026-06-06]",
            dictionaryInfo,
            buildDictionaryStylesMap(dictionaryInfo),
        );

        assert.equal(input.resultOutputMode, "group");
        assert.equal(
            input.cardFormat.fields.Definition.value,
            "{single-glossary-jitendexorg-2026-06-06}",
        );
        assert.equal(
            input.dictionaryStylesMap?.get("Jitendex.org [2026-06-06]"),
            ".term-glossary-list { color: red; }",
        );
    });

    it("returns Yomitan-generated grouped glossary HTML for related words", async () => {
        const dictionaryInfo = [
            createDictionarySummary("Jitendex.org [2026-06-06]"),
        ];
        const fakeCore = {
            buildAnkiFieldsFromDictionaryEntry: async () => ({
                fields: {
                    Definition:
                        '<div class="yomitan-glossary"><ol><li data-dictionary="Jitendex.org [2026-06-06]"><span class="structured-content">to exceed</span><style>.yomitan-glossary [data-dictionary="Jitendex.org [2026-06-06]"] .term-glossary-list { color: red; }</style></li></ol></div>',
                },
                errors: [],
            }),
        } as unknown as YomitanCoreLike;

        const html = await renderRelatedWordEntryHtml(
            createTermEntry(),
            "超える",
            fakeCore,
            dictionaryInfo,
            ["Jitendex"],
            buildDictionaryStylesMap(dictionaryInfo),
        );

        assert.match(html, /<ol>/);
        assert.match(
            html,
            /<li data-dictionary="Jitendex\.org \[2026-06-06\]">/,
        );
        assert.match(html, /class="structured-content"/);
        assert.match(html, /<style>/);
        assert.doesNotMatch(html, /lapis-lookup-definition-entry/);
    });

    it("does not override Yomitan glossary layout in lookup CSS", () => {
        const css = fs.readFileSync("../../src/styling.css", "utf8");
        const backTemplate = fs.readFileSync("../../src/back.html", "utf8");

        assert.match(
            backTemplate,
            /detail\.className = "lapis-lookup-word-detail definition"/,
        );
        assert.match(backTemplate, /src="_lapis_lookup_store\.js"/);
        assert.equal(
            [...backTemplate.matchAll(/src="_lapis_lookup_store[^"]*\.js"/g)]
                .length,
            1,
        );
        assert.match(backTemplate, /function stableLookupHash/);
        assert.match(backTemplate, /function loadLookupShard/);
        assert.match(backTemplate, /shardPromises: new Map\(\)/);
        assert.doesNotMatch(
            backTemplate,
            /loadLegacySharedLookupTerms|__lapisLookupCompressedStore|legacyTerms/,
        );
        assert.match(backTemplate, /Array\.isArray\(kanjiItem\.relatedWords\)/);
        assert.match(backTemplate, /kanjiItem\.wordRefs/);
        assert.match(backTemplate, /function createKanjiComponentCluster/);
        assert.match(backTemplate, /id="lapis-lookup-kanji-components"/);
        assert.doesNotMatch(
            css,
            /\.lapis-lookup-word-detail \.yomitan-glossary ul/,
        );
        assert.doesNotMatch(css, /lapis-lookup-definition-entry/);
    });
});

function createTermEntry(): TermDictionaryEntry {
    return {
        headwords: [{ term: "超える", reading: "こえる" }],
        definitions: [
            {
                dictionary: "Jitendex.org [2026-06-06]",
                dictionaryAlias: "Jitendex.org [2026-06-06]",
            },
        ],
        frequencies: [],
    };
}
