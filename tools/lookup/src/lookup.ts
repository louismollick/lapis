import "fake-indexeddb/auto";
import {
    DEFAULT_DEFINITION_DICTIONARY_NAMES,
    DEFAULT_FREQUENCY_DICTIONARY_NAMES,
    DEFAULT_MAX_WORDS_PER_KANJI,
} from "./constants.js";
import {
    buildDictionaryStylesMap,
    buildKanjiDictionaryMap,
    buildTermDictionaryMap,
    ensureDictionaryArchivesPresent,
    importSuggestedDictionaries,
    selectPreferredDictionaryTitle,
    selectPreferredFrequency,
} from "./dictionaries.js";
import { getRelatedWordsForKanji } from "./kanji-provider.js";
import { renderFallbackKanjiHtml, renderSelectedEntryHtml } from "./render.js";
import type {
    LookupCardPayload,
    LookupCliInput,
    LookupCliInputItem,
    LookupCliOutput,
    LookupCliResultItem,
    LookupRelatedWordPayload,
} from "./types.js";
import type {
    BuildAnkiNoteResult,
    DictionarySummary,
    KanjiDictionaryEntry,
    TermDictionaryEntry,
    YomitanCoreLike,
} from "./yomitan-types.js";
import { createYomitanCore } from "./yomitan.js";

type LookupRuntime = {
    core: YomitanCoreLike;
    dictionaryInfo: DictionarySummary[];
    dictionaryStylesMap: Map<string, string>;
    termDictionaryMap: ReturnType<typeof buildTermDictionaryMap>;
    kanjiDictionaryMap: ReturnType<typeof buildKanjiDictionaryMap>;
};

export async function runLookup(
    input: LookupCliInput,
): Promise<LookupCliOutput> {
    await ensureDictionaryArchivesPresent();
    const runtime = await createRuntime();

    try {
        const results: LookupCliResultItem[] = [];
        for (const item of input.items) {
            results.push(
                await buildLookupResult(item, runtime, {
                    maxWordsPerKanji:
                        input.maxWordsPerKanji ?? DEFAULT_MAX_WORDS_PER_KANJI,
                    definitionDictionaryNames:
                        input.definitionDictionaryNames ??
                        DEFAULT_DEFINITION_DICTIONARY_NAMES,
                    frequencyDictionaryNames:
                        input.frequencyDictionaryNames ??
                        DEFAULT_FREQUENCY_DICTIONARY_NAMES,
                }),
            );
        }

        return { results };
    } finally {
        await runtime.core.dispose();
    }
}

async function createRuntime(): Promise<LookupRuntime> {
    const core = await createYomitanCore(
        `lapis-lookup-${Date.now()}-${process.pid}`,
    );
    await core.initialize();

    const dictionaryInfo = await importSuggestedDictionaries(core);
    return {
        core,
        dictionaryInfo,
        dictionaryStylesMap: buildDictionaryStylesMap(dictionaryInfo),
        termDictionaryMap: buildTermDictionaryMap(dictionaryInfo),
        kanjiDictionaryMap: buildKanjiDictionaryMap(dictionaryInfo),
    };
}

async function buildLookupResult(
    item: LookupCliInputItem,
    runtime: LookupRuntime,
    options: {
        maxWordsPerKanji: number;
        definitionDictionaryNames: string[];
        frequencyDictionaryNames: string[];
    },
): Promise<LookupCliResultItem> {
    const { noteId, expression, mode } = item;
    const warnings: string[] = [];
    let generatedFields: Record<string, string> | undefined;

    if (mode === "convertLegacy") {
        const generatedNote = await generateLapisFields(expression, runtime);
        if (generatedNote.status === "no-entry") {
            return {
                noteId,
                mode,
                status: "skipped",
                expression,
                warnings: [
                    `Skipped note ${noteId}: no Yomitan entry for "${expression}".`,
                    ...generatedNote.errors,
                ],
            };
        }
        warnings.push(...generatedNote.errors);
        generatedFields = generatedNote.fields;
    }

    const payload = await buildLookupPayload(
        expression,
        runtime,
        options,
        warnings,
    );

    return {
        noteId,
        mode,
        status: "ok",
        expression,
        generatedFields,
        payload,
        warnings,
    };
}

async function buildLookupPayload(
    expression: string,
    runtime: LookupRuntime,
    options: {
        maxWordsPerKanji: number;
        definitionDictionaryNames: string[];
        frequencyDictionaryNames: string[];
    },
    warnings: string[],
): Promise<LookupCardPayload> {
    const kanjiCharacters = extractUniqueKanji(expression);
    const payload: LookupCardPayload = {
        version: 1,
        expression,
        kanji: [],
    };

    for (const character of kanjiCharacters) {
        const relatedWords = await getRelatedWordsForKanji(character);
        const limitedWords = relatedWords.slice(0, options.maxWordsPerKanji);
        const wordPayloads: LookupRelatedWordPayload[] = [];

        for (const word of limitedWords) {
            const relatedWordPayload = await resolveRelatedWord(
                word,
                runtime,
                options,
                warnings,
            );
            wordPayloads.push(relatedWordPayload);
        }

        payload.kanji.push({
            char: character,
            relatedWords: wordPayloads,
        });
    }

    return payload;
}

async function generateLapisFields(
    expression: string,
    runtime: LookupRuntime,
): Promise<BuildAnkiNoteResult> {
    const dictionaries = runtime.dictionaryInfo.map((dictionary) => ({
        name: dictionary.title,
        enabled: true,
    }));

    return runtime.core.buildAnkiNoteFromTerm({
        term: expression,
        enabledDictionaryMap: runtime.termDictionaryMap,
        dictionaries,
        dictionaryInfo: runtime.dictionaryInfo,
        additionalTemplates: buildLapisAdditionalTemplates(
            runtime.dictionaryInfo,
        ),
        cardFormat: {
            deck: "Lapis",
            model: "Lapis+Lookup",
            fields: Object.fromEntries(
                Object.entries(
                    buildLapisFieldTemplates(runtime.dictionaryInfo),
                ).map(([fieldName, value]) => [fieldName, { value }]),
            ),
        },
        context: {
            url: "",
            query: expression,
            fullQuery: expression,
            documentTitle: "",
        },
        options: {
            matchType: "exact",
            deinflect: true,
            removeNonJapaneseCharacters: false,
        },
    });
}

function buildLapisFieldTemplates(
    dictionaryInfo: DictionarySummary[],
): Record<string, string> {
    return {
        Expression: "{expression}",
        ExpressionFurigana: "{furigana-plain}",
        ExpressionReading: "{reading}",
        ExpressionAudio: "{audio}",
        SelectionText: "{popup-selection-text}",
        MainDefinition: "{lapis-main-definition}",
        Sentence: "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}",
        Glossary: "{glossary}",
        PitchPosition: "{pitch-accent-positions}",
        PitchCategories: "{pitch-accent-categories}",
        Frequency: "{frequencies}",
        FreqSort: "{frequency-harmonic-rank}",
        MiscInfo: "{document-title}",
    };
}

function buildLapisAdditionalTemplates(
    dictionaryInfo: DictionarySummary[],
): string {
    const titleMap = new Map(
        dictionaryInfo.map((dictionary) => [
            normalizeDictionaryTitle(dictionary.title),
            dictionary.title,
        ]),
    );
    const preferredTitles = [
        titleMap.get("jitendex") ?? "",
        titleMap.get("jmdict") ?? "",
    ].filter(Boolean);
    const preferredBlocks = preferredTitles
        .map((title) => buildPreferredDefinitionBlock(title))
        .join("\n");

    return `
{{#*inline "lapis-main-definition"}}
    {{~#scope~}}
        {{~set "rendered" false~}}
        {{~#if (op "===" definition.type "term")~}}
            {{~#if definition.glossary.[0]~}}
                {{{formatGlossaryPlain definition.dictionary definition.glossary.[0]}}}
                {{~set "rendered" true~}}
            {{~/if~}}
        {{~else if (op "||" (op "===" definition.type "termGrouped") (op "===" definition.type "termMerged"))~}}
${preferredBlocks}
            {{~#unless (get "rendered")~}}
                {{~#with definition.definitions.[0]~}}
                    {{~#if glossary.[0]~}}
                        {{{formatGlossaryPlain dictionary glossary.[0]}}}
                    {{~/if~}}
                {{~/with~}}
            {{~/unless~}}
        {{~/if~}}
    {{~/scope~}}
{{/inline}}
`.trim();
}

function buildPreferredDefinitionBlock(title: string): string {
    const escapedTitle = escapeHandlebarsString(title);
    return `
            {{~#each definition.definitions~}}
                {{~#if (op "&&" (op "!" (get "rendered")) (op "||" (op "===" dictionary "${escapedTitle}") (op "===" dictionaryAlias "${escapedTitle}")))~}}
                    {{~#if glossary.[0]~}}
                        {{{formatGlossaryPlain dictionary glossary.[0]}}}
                        {{~set "rendered" true~}}
                    {{~/if~}}
                {{~/if~}}
            {{~/each~}}`.trimEnd();
}

function normalizeDictionaryTitle(value: string): string {
    const lowered = value.toLowerCase();
    if (lowered.includes("jitendex")) {
        return "jitendex";
    }
    if (lowered.includes("jmdict")) {
        return "jmdict";
    }
    return lowered;
}

function toKebabCase(value: string): string {
    return value
        .replace(/[\s_\u3000]/g, "-")
        .replace(/[^\p{L}\p{N}-]/gu, "")
        .replace(/--+/g, "-")
        .replace(/^-|-$/g, "")
        .toLowerCase();
}

function escapeHandlebarsString(value: string): string {
    return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

async function resolveRelatedWord(
    word: string,
    runtime: LookupRuntime,
    options: {
        definitionDictionaryNames: string[];
        frequencyDictionaryNames: string[];
    },
    warnings: string[],
): Promise<LookupRelatedWordPayload> {
    const termEntry = await lookupBestTermEntry(word, runtime);
    if (termEntry) {
        const frequency = selectPreferredFrequency(
            termEntry.frequencies.map((item) => ({
                dictionary: item.dictionary,
                dictionaryAlias: item.dictionaryAlias,
                frequency: item.frequency,
            })),
            options.frequencyDictionaryNames,
        );

        return {
            term: termEntry.headwords[0]?.term ?? word,
            reading: termEntry.headwords[0]?.reading ?? "",
            frequency,
            entryHtml: await renderSelectedEntryHtml(
                termEntry,
                runtime.dictionaryStylesMap,
                options.definitionDictionaryNames,
            ),
        };
    }

    if ([...word].length === 1) {
        const kanjiEntry = await lookupBestKanjiEntry(
            word,
            runtime,
            options.definitionDictionaryNames,
        );
        if (kanjiEntry) {
            return {
                term: word,
                reading: joinKanjiReadings(kanjiEntry),
                frequency: { value: null, source: null },
                entryHtml: renderFallbackKanjiHtml(kanjiEntry),
            };
        }
    }

    warnings.push(`No dictionary entry found for related word "${word}".`);
    return {
        term: word,
        reading: "",
        frequency: { value: null, source: null },
        entryHtml: `<div class="lapis-lookup-empty">No dictionary entry found for ${escapeHtml(word)}.</div>`,
    };
}

async function lookupBestTermEntry(
    word: string,
    runtime: LookupRuntime,
): Promise<TermDictionaryEntry | null> {
    const lookup = await runtime.core.findTerms(word, {
        enabledDictionaryMap: runtime.termDictionaryMap,
        options: {
            matchType: "exact",
            deinflect: true,
            removeNonJapaneseCharacters: false,
        },
    });

    const entries = lookup.entries;
    if (entries.length === 0) {
        return null;
    }

    return (
        entries.find((entry) =>
            entry.headwords.some((headword) => headword.term === word),
        ) ??
        entries.find((entry) =>
            entry.headwords.some((headword) => headword.term.includes(word)),
        ) ??
        entries[0] ??
        null
    );
}

async function lookupBestKanjiEntry(
    word: string,
    runtime: LookupRuntime,
    preferredDefinitionNames: string[],
): Promise<KanjiDictionaryEntry | null> {
    const entries = await runtime.core.findKanji(word, {
        enabledDictionaryMap: runtime.kanjiDictionaryMap,
    });

    if (entries.length === 0) {
        return null;
    }

    const availableTitles = entries.map(
        (entry) => entry.dictionaryAlias || entry.dictionary,
    );
    const selectedTitle = selectPreferredDictionaryTitle(
        availableTitles,
        preferredDefinitionNames,
    );
    return (
        entries.find(
            (entry) =>
                (entry.dictionaryAlias || entry.dictionary) === selectedTitle,
        ) ??
        entries[0] ??
        null
    );
}

function extractUniqueKanji(expression: string): string[] {
    const uniqueCharacters = new Set<string>();
    for (const character of expression) {
        if (/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(character)) {
            uniqueCharacters.add(character);
        }
    }
    return [...uniqueCharacters];
}

function joinKanjiReadings(entry: KanjiDictionaryEntry): string {
    return [...entry.onyomi, ...entry.kunyomi].filter(Boolean).join(" / ");
}

function escapeHtml(value: string): string {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
